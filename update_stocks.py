import requests
import json
import os
import pandas as pd
from datetime import datetime

DB_FILE = "historical_prices.json"
OUTPUT_FILE = "all_stocks_data.json"

def get_today_quotes():
    """只抓取今天的全市場收盤大表 (只需要 2 個 API Request)"""
    today_data = {}
    
    # 抓上市今日收盤
    try:
        res = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
        for item in res.json():
            code = str(item.get("Code", "")).strip()
            close = str(item.get("ClosingPrice", "")).replace(',', '')
            vol = str(item.get("TradeVolume", "")).replace(',', '')
            if close and vol and close.replace('.', '', 1).isdigit() and len(code) == 4:
                today_data[code] = {"close": float(close), "volume": float(vol) / 1000}
    except Exception as e:
        print(f"獲取上市今日行情失敗: {e}")

    # 抓上櫃今日收盤
    try:
        res = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        for item in res.json():
            code = str(item.get("SecuritiesCompanyCode", "")).strip()
            close = str(item.get("Close", "")).replace(',', '')
            vol = str(item.get("TradingShares", "")).replace(',', '')
            if close and vol and close.replace('.', '', 1).isdigit() and len(code) == 4:
                today_data[code] = {"close": float(close), "volume": float(vol) / 1000}
    except Exception as e:
        print(f"獲取上櫃今日行情失敗: {e}")

    return today_data

def is_ma200_up_10days(ma200_list):
    if len(ma200_list) < 10: return False
    last_10 = ma200_list[-10:]
    for i in range(1, 10):
        if last_10[i] <= last_10[i-1]:
            return False
    return True

def main():
    print("=== 開始每日極速增量更新 ===")
    
    # 1. 讀取歷史資料庫
    if not os.path.exists(DB_FILE):
        print(f"找不到 {DB_FILE}，請先上傳歷史資料庫！")
        return
        
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    # 2. 獲取今天全市場最新價格
    today_quotes = get_today_quotes()
    if not today_quotes:
        print("今日無資料或 API 異常，結束更新。")
        return
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_stocks_result = []
    updated_count = 0

    # 3. 更新資料庫並計算指標
    for code, info in db.items():
        if code in today_quotes:
            new_quote = today_quotes[code]
            
            # 如果今天已經更新過了，就覆蓋最後一筆 (防止重複執行導致塞入兩筆)
            if info["history"] and info["history"][-1]["date"] == today_str:
                info["history"][-1] = {"date": today_str, "close": new_quote["close"], "volume": new_quote["volume"]}
            else:
                info["history"].append({"date": today_str, "close": new_quote["close"], "volume": new_quote["volume"]})
            
            # 保持資料庫最多只存 250 天，避免檔案無限變大
            info["history"] = info["history"][-250:]
            updated_count += 1

        history = info["history"]
        if len(history) < 220:
            continue # 天數不足算不出 MA200

        # 將歷史收盤價轉為 pandas Series 計算均線
        closes = pd.Series([x["close"] for x in history])
        
        ma5 = closes.rolling(window=5).mean()
        ma20 = closes.rolling(window=20).mean()
        ma60 = closes.rolling(window=60).mean()
        ma200 = closes.rolling(window=200).mean()
        low20 = closes.rolling(window=20).min()
        
        ma200_up = is_ma200_up_10days(ma200.dropna().tolist())

        all_stocks_result.append({
            "code": code,
            "name": info["name"],
            "market": info["market"],
            "close": round(history[-1]["close"], 2),
            "ma5": round(ma5.iloc[-1], 2),
            "ma20": round(ma20.iloc[-1], 2),
            "ma60": round(ma60.iloc[-1], 2),
            "ma200": round(ma200.iloc[-1], 2),
            "lowestClose20": round(low20.iloc[-2] if len(low20) >= 2 else low20.iloc[-1], 2),
            "volume": round(history[-1]["volume"], 2),
            "ma200_up_10days": ma200_up
        })

    # 4. 存回歷史資料庫 (接龍後的結果)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)

    # 5. 輸出給網站用的最終分析結果
    output_data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_valid_stocks": len(all_stocks_result),
        "stocks": all_stocks_result
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"=== 更新完成 ===")
    print(f"今天共更新 {updated_count} 檔股票價格")
    print(f"成功儲存 {len(all_stocks_result)} 檔符合天數的股票指標！")

if __name__ == "__main__":
    main()
