import requests
import json
import os
import yfinance as yf
import pandas as pd
from datetime import datetime

# 1. 抓取上市 + 上櫃清單
def fetch_all_stock_list():
    stocks = []
    seen_codes = set()

    # 抓上市
    try:
        url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res = requests.get(url_twse, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                code = str(item.get("Code", "")).strip()
                name = str(item.get("Name", "")).strip()
                if len(code) == 4 and code.isdigit() and code not in seen_codes:
                    stocks.append({"code": code, "name": name, "market": "上市"})
                    seen_codes.add(code)
    except Exception as e:
        print(f"上市清單失敗: {e}")

    # 抓上櫃
    try:
        url_tpex = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        res = requests.get(url_tpex, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                code = str(item.get("SecuritiesCompanyCode", "")).strip()
                name = str(item.get("CompanyName", "")).strip()
                if len(code) == 4 and code.isdigit() and code not in seen_codes:
                    stocks.append({"code": code, "name": name, "market": "上櫃"})
                    seen_codes.add(code)
    except Exception as e:
        print(f"上櫃清單失敗: {e}")

    return stocks

# 判斷 MA200 是否連續 10 天上升
def is_ma200_up_10days(ma200_series):
    # 取最後 10 天的 MA200
    last_10 = ma200_series.tail(10).tolist()
    if len(last_10) < 10 or pd.isna(last_10).any():
        return False
    
    for i in range(1, 10):
        if last_10[i] <= last_10[i-1]:
            return False
    return True

def main():
    print("=== 開始獲取台股清單 ===")
    stocks_info = fetch_all_stock_list()
    
    if not stocks_info:
        print("無法取得股票清單")
        return

    print(f"共取得 {len(stocks_info)} 檔普通股。開始透過 yfinance 批次下載...")

    # 把台灣股號轉換成 yfinance 看得懂的格式 (上市加 .TW，上櫃加 .TWO)
    # yfinance 下載有限制字串長度，我們分批下載，每次 200 檔
    batch_size = 200
    all_tickers = []
    ticker_to_info = {}

    for s in stocks_info:
        # yf 格式：台積電是 2330.TW，元太是 8069.TWO
        suffix = ".TW" if s["market"] == "上市" else ".TWO"
        yf_ticker = f"{s['code']}{suffix}"
        all_tickers.append(yf_ticker)
        ticker_to_info[yf_ticker] = s

    results = []
    checked_count = 0

    # 批次下載歷史股價 (抓過去 1 年的資料，因為要算 200 MA，一年約 250 個交易日)
    for i in range(0, len(all_tickers), batch_size):
        batch_tickers = all_tickers[i:i + batch_size]
        print(f"下載進度: 處理第 {i+1} 到 {i+len(batch_tickers)} 檔...")
        
        # threads=True 讓 yfinance 平行下載，速度極快
        data = yf.download(batch_tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=False, prepost=False, threads=True, progress=False)

        for ticker in batch_tickers:
            checked_count += 1
            info = ticker_to_info[ticker]
            
            try:
                # 處理單檔與多檔時 pandas 回傳結構不同的問題
                if len(batch_tickers) == 1:
                    df = data.copy()
                else:
                    df = data[ticker].copy()
                
                df = df.dropna(subset=['Close', 'Volume'])
                if len(df) < 220: # 交易日不足以算 200MA
                    continue

                close_series = df['Close']
                volume_series = df['Volume']

                # 計算 MA
                ma5 = close_series.rolling(window=5).mean()
                ma20 = close_series.rolling(window=20).mean()
                ma60 = close_series.rolling(window=60).mean()
                ma200 = close_series.rolling(window=200).mean()
                
                # 20日最低收盤價
                lowest_close_20 = close_series.rolling(window=20).min()

                # 最新一天的資料
                latest_close = close_series.iloc[-1]
                latest_vol = volume_series.iloc[-1] / 1000  # 轉成張數
                
                c_ma5 = ma5.iloc[-1]
                c_ma20 = ma20.iloc[-1]
                c_ma60 = ma60.iloc[-1]
                c_ma200 = ma200.iloc[-1]
                c_low20 = lowest_close_20.iloc[-2] # 過去20日(不含今天)的最低，或含今天依你策略而定。若是包含今天就用 iloc[-1]
                
                # 排除缺值
                if pd.isna(c_ma5) or pd.isna(c_ma20) or pd.isna(c_ma60) or pd.isna(c_ma200):
                    continue

                ma200_up = is_ma200_up_10days(ma200)

                # 你的策略條件
                passed = (
                    latest_close > c_ma5 and 
                    latest_close > c_ma20 and 
                    latest_close > c_ma60 and
                    c_low20 < c_ma20 and
                    latest_vol > 500 and
                    latest_close < c_ma200 * 1.4 and
                    ma200_up
                )

                if passed:
                    results.append({
                        "code": info["code"],
                        "name": info["name"],
                        "market": info["market"],
                        "close": round(latest_close, 2),
                        "ma5": round(c_ma5, 2),
                        "ma20": round(c_ma20, 2),
                        "ma60": round(c_ma60, 2),
                        "ma200": round(c_ma200, 2),
                        "lowestClose20": round(c_low20, 2),
                        "volume": round(latest_vol, 2),
                    })
                    print(f"🔥 找到符合標的: {info['code']} {info['name']}")

            except Exception as e:
                # 該股票可能下市或無資料，略過
                continue

    # 寫入 json
    output_data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checked_count": checked_count,
        "matched_count": len(results),
        "stocks": results
    }

    with open("stocks.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("=== 掃描完成 ===")
    print(f"總計掃描: {checked_count} 檔，符合條件: {len(results)} 檔。")

if __name__ == "__main__":
    main()
