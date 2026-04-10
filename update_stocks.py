import requests
import json
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

DB_FILE = "historical_prices.json"
OUTPUT_FILE = "all_stocks_data.json"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"


def parse_tpex_date(date_str):
    date_str = str(date_str).strip()
    if len(date_str) == 7 and date_str.isdigit():
        year = int(date_str[:3]) + 1911
        return f"{year}-{date_str[3:5]}-{date_str[5:7]}"
    return None


def get_last_trading_date_from_twse():
    tw_now = datetime.now(tz=pytz.timezone("Asia/Taipei"))
    for month_offset in range(2):
        check_dt = tw_now - timedelta(days=30 * month_offset)
        ym = check_dt.strftime("%Y%m")
        try:
            url = f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={ym}01&response=json"
            res = requests.get(url, timeout=10)
            data = res.json()
            for row in reversed(data.get("data", [])):
                parts = str(row[0]).strip().split("/")
                if len(parts) == 3:
                    year = int(parts[0]) + 1911
                    candidate = f"{year}-{parts[1]}-{parts[2]}"
                    if candidate <= tw_now.strftime("%Y-%m-%d"):
                        return candidate
        except Exception as e:
            print(f"TWSE 月曆查詢失敗: {e}")
    return None


def get_today_quotes():
    """
    三個來源取得今日報價：
    1. TPEX openapi（上櫃，收盤後即時更新）
    2. TWSE STOCK_DAY_ALL（上市，afterTrading 版，收盤後即時更新）★ 新增
    3. TWSE openapi（備援）
    回傳 today_data, quote_dates, actual_date
    """
    today_data = {}
    quote_dates = {}
    actual_date = None
    tw_today = datetime.now(tz=pytz.timezone("Asia/Taipei")).strftime("%Y-%m-%d")

    # ① TPEX 上櫃
    try:
        res = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
        for item in res.json():
            code = str(item.get("SecuritiesCompanyCode", "")).strip()
            close = str(item.get("Close", "")).replace(",", "")
            vol = str(item.get("TradingShares", "")).replace(",", "")
            date_str = str(item.get("Date", "")).strip()
            if close and vol and close.replace(".", "", 1).isdigit() and len(code) == 4:
                parsed = parse_tpex_date(date_str)
                today_data[code] = {"close": float(close), "volume": float(vol) / 1000}
                quote_dates[code] = parsed
                if parsed and (actual_date is None or parsed > actual_date):
                    actual_date = parsed
        print(f"  TPEX: {sum(1 for c in quote_dates if quote_dates[c] == actual_date)} 檔")
    except Exception as e:
        print(f"TPEX 行情失敗: {e}")

    # ② TWSE afterTrading 全市場收盤（一次請求拿全部，收盤後即時更新）
    try:
        date_nodash = tw_today.replace("-", "")
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json&date={date_nodash}"
        res = requests.get(url, timeout=15)
        data = res.json()
        if data.get("stat") == "OK":
            raw_date = data.get("date", "")  # 格式 "20260410"
            if len(raw_date) == 8:
                parsed_twse = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            else:
                parsed_twse = actual_date
            count = 0
            for row in data.get("data", []):
                if len(row) < 8:
                    continue
                code = str(row[0]).strip()
                close_raw = str(row[7]).replace(",", "").strip()
                vol_raw = str(row[2]).replace(",", "").strip()
                if len(code) == 4 and close_raw.replace(".", "", 1).isdigit() and vol_raw.isdigit():
                    today_data[code] = {"close": float(close_raw), "volume": float(vol_raw) / 1000}
                    quote_dates[code] = parsed_twse
                    count += 1
            if parsed_twse and (actual_date is None or parsed_twse > actual_date):
                actual_date = parsed_twse
            print(f"  TWSE afterTrading: {count} 檔（日期: {parsed_twse}）")
        else:
            print(f"  TWSE afterTrading 尚未更新（stat={data.get('stat')}），改用 openapi 備援")
            raise ValueError("TWSE afterTrading not ready")
    except Exception as e:
        # ③ TWSE openapi 備援
        try:
            res = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
            count = 0
            for item in res.json():
                code = str(item.get("Code", "")).strip()
                close = str(item.get("ClosingPrice", "")).replace(",", "")
                vol = str(item.get("TradeVolume", "")).replace(",", "")
                date_str = str(item.get("Date", "")).strip()
                if close and vol and close.replace(".", "", 1).isdigit() and len(code) == 4:
                    parsed = parse_tpex_date(date_str)
                    today_data[code] = {"close": float(close), "volume": float(vol) / 1000}
                    quote_dates[code] = parsed
                    if parsed and (actual_date is None or parsed > actual_date):
                        actual_date = parsed
                    count += 1
            print(f"  TWSE openapi 備援: {count} 檔")
        except Exception as e2:
            print(f"TWSE 備援失敗: {e2}")

    if actual_date is None:
        print("警告: 查詢 TWSE 月曆...")
        actual_date = get_last_trading_date_from_twse()
        if not actual_date:
            return {}, {}, None

    print(f"實際交易日期: {actual_date}")
    return today_data, quote_dates, actual_date


def clean_duplicate_entries(db, actual_data_date):
    cleaned = 0
    for info in db.values():
        h = info.get("history", [])
        if (len(h) >= 2 and h[-1]["date"] == actual_data_date and
                round(h[-2]["close"], 2) == round(h[-1]["close"], 2) and
                round(h[-2]["volume"], 2) == round(h[-1]["volume"], 2)):
            info["history"] = h[:-1]
            cleaned += 1
    return cleaned


# ── FinMind 補缺（只補仍然缺漏的） ────────────────────────────────────────────

def fetch_finmind(code, start_date, end_date, token=""):
    params = {"dataset": "TaiwanStockPrice", "data_id": code,
              "start_date": start_date, "end_date": end_date}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        res = requests.get(FINMIND_API_URL, params=params, headers=headers, timeout=20)
        data = res.json()
        if data.get("status") != 200:
            return []
        rows = []
        for item in data.get("data", []):
            dv, cv, vv = item.get("date"), item.get("close"), item.get("Trading_Volume")
            if dv and cv is not None:
                rows.append({"date": dv, "close": round(float(cv), 2),
                             "volume": round(float(vv) / 1000, 2) if vv else 0.0})
        return rows
    except Exception as e:
        print(f"  [{code}] FinMind 失敗: {e}")
        return []


def backfill_finmind(db, actual_data_date, token=""):
    stale = [code for code, info in db.items()
             if info.get("history") and info["history"][-1]["date"] < actual_data_date]

    if not stale:
        print("FinMind：無需補齊。")
        return db

    print(f"FinMind 補齊：{len(stale)} 檔...")
    filled = 0
    sleep_sec = 6 if token else 12

    for i, code in enumerate(stale):
        last_date = db[code]["history"][-1]["date"]
        start_dt = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = fetch_finmind(code, start_dt, actual_data_date, token=token)

        if rows:
            existing = {r["date"] for r in db[code]["history"]}
            for row in rows:
                if row["date"] not in existing:
                    db[code]["history"].append(row)
                else:
                    for j, h in enumerate(db[code]["history"]):
                        if h["date"] == row["date"]:
                            db[code]["history"][j] = row
                            break
            db[code]["history"] = sorted(db[code]["history"], key=lambda x: x["date"])[-250:]
            filled += 1

        if (i + 1) % 50 == 0:
            print(f"  進度: {i+1}/{len(stale)} | 補齊 {filled}")
        time.sleep(sleep_sec)

    print(f"FinMind 完成：補齊 {filled} 檔")
    return db


# ── 技術指標 ──────────────────────────────────────────────────────────────────

def is_ma200_up_10days(ma200_list):
    if len(ma200_list) < 10:
        return False
    last_10 = ma200_list[-10:]
    return all(last_10[i] > last_10[i - 1] for i in range(1, 10))


def calculate_kd(df, n=9):
    low_min = df["close"].rolling(window=n, min_periods=1).min()
    high_max = df["close"].rolling(window=n, min_periods=1).max()
    rsv = (df["close"] - low_min) / (high_max - low_min + 1e-8) * 100
    K = np.zeros(len(df))
    D = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0:
            K[i] = D[i] = 50
        else:
            K[i] = K[i-1] * 2/3 + rsv.iloc[i] * 1/3
            D[i] = D[i-1] * 2/3 + K[i] * 1/3
    return pd.Series(K, index=df.index), pd.Series(D, index=df.index)


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    print("=== 開始每日極速增量更新 ===")

    if not os.path.exists(DB_FILE):
        print(f"找不到 {DB_FILE}！")
        return

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    # STEP 1: 取得今日報價
    today_quotes, quote_dates, actual_data_date = get_today_quotes()
    if not today_quotes or actual_data_date is None:
        print("今日無資料或非交易日，結束。")
        return

    # STEP 2: 偵測並清除重複寫入的錯誤資料
    already_updated = sum(1 for info in db.values()
                          if info.get("history") and info["history"][-1]["date"] == actual_data_date)
    if already_updated > len(db) * 0.8:
        dup_count = sum(
            1 for info in db.values()
            if info.get("history") and len(info["history"]) >= 2
            and info["history"][-1]["date"] == actual_data_date
            and round(info["history"][-2]["close"], 2) == round(info["history"][-1]["close"], 2)
            and round(info["history"][-2]["volume"], 2) == round(info["history"][-1]["volume"], 2)
        )
        if dup_count > len(db) * 0.1:
            cleaned = clean_duplicate_entries(db, actual_data_date)
            print(f"清除 {cleaned} 筆重複資料，重新更新...")
        else:
            print(f"已有 {already_updated} 檔為 {actual_data_date}，資料已是最新，跳過。")
            return

    # STEP 3: 寫入 TPEX / TWSE 資料（用 api_date 判斷，不比對 close/volume）
    updated_count = 0
    skipped_old = 0
    for code, info in db.items():
        if code not in today_quotes:
            continue
        new_quote = today_quotes[code]
        history = info["history"]
        api_date = quote_dates.get(code)

        if api_date is None or (history and api_date <= history[-1]["date"]):
            skipped_old += 1
            continue

        if history and history[-1]["date"] == api_date:
            history[-1] = {"date": api_date, **new_quote}
        else:
            history.append({"date": api_date, **new_quote})
        info["history"] = history[-250:]
        updated_count += 1

    print(f"TPEX/TWSE 更新：{updated_count} 檔")
    if skipped_old:
        print(f"API 日期未更新，跳過：{skipped_old} 檔")

    # STEP 4: FinMind 補缺仍落後的股票
    finmind_token = os.environ.get("FINMIND_TOKEN", "")
    still_stale = sum(1 for info in db.values()
                      if info.get("history") and info["history"][-1]["date"] < actual_data_date)
    if still_stale:
        if finmind_token:
            db = backfill_finmind(db, actual_data_date, token=finmind_token)
        else:
            print(f"未設定 FINMIND_TOKEN，{still_stale} 檔無法補齊。")

    # STEP 5: 計算技術指標
    all_stocks_result = []
    for code, info in db.items():
        history = info["history"]
        if len(history) < 220:
            continue
        df = pd.DataFrame(history)
        closes, volumes = df["close"], df["volume"]
        ma5   = closes.rolling(5).mean()
        ma20  = closes.rolling(20).mean()
        ma60  = closes.rolling(60).mean()
        ma200 = closes.rolling(200).mean()
        low20 = closes.rolling(20).min()
        ma200_up        = is_ma200_up_10days(ma200.dropna().tolist())
        ma20_today      = ma20.iloc[-1]
        ma20_yesterday  = ma20.iloc[-2] if len(ma20) > 1 else ma20_today
        vol_ma20        = volumes.rolling(20).mean()
        has_vol_burst   = any(volumes.iloc[-10:].iloc[i] > vol_ma20.iloc[-10:].iloc[i] * 2 for i in range(10))
        has_price_burst = any(closes.pct_change().iloc[-10:] * 100 > 5.0)
        high5     = closes.rolling(5).max()
        bias20    = abs(closes.iloc[-1] - ma20_today) / ma20_today * 100 if ma20_today > 0 else 0
        vol_ma5   = volumes.rolling(5).mean()
        max_vol10 = volumes.iloc[-10:].max()
        K, D = calculate_kd(df)
        all_stocks_result.append({
            "code": code, "name": info["name"], "market": info["market"],
            "close": round(float(closes.iloc[-1]), 2),
            "volume": round(float(volumes.iloc[-1]), 2),
            "ma5": round(float(ma5.iloc[-1]), 2),
            "ma20": round(float(ma20_today), 2),
            "ma60": round(float(ma60.iloc[-1]), 2),
            "ma200": round(float(ma200.iloc[-1]), 2),
            "lowestClose20": round(float(low20.iloc[-2] if len(low20) >= 2 else low20.iloc[-1]), 2),
            "ma200_up_10days": ma200_up,
            "ma20_yesterday": round(float(ma20_yesterday), 2),
            "has_vol_burst_10d": bool(has_vol_burst),
            "has_price_burst_10d": bool(has_price_burst),
            "highestClose5": round(float(high5.iloc[-1]), 2),
            "bias20": round(float(bias20), 2),
            "vol_ma5": round(float(vol_ma5.iloc[-1]), 2),
            "max_vol_10d": round(float(max_vol10), 2),
            "k_value": round(float(K.iloc[-1]), 2),
        })

    # STEP 6: 儲存
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)

    tw_now = datetime.now(tz=pytz.timezone("Asia/Taipei"))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": tw_now.strftime("%Y-%m-%d %H:%M:%S CST"),
            "data_date": actual_data_date,
            "total_valid_stocks": len(all_stocks_result),
            "stocks": all_stocks_result,
        }, f, ensure_ascii=False, indent=2)

    print(f"=== 更新完成 ===")
    print(f"TPEX/TWSE: {updated_count} 檔 | 實際日期: {actual_data_date}")
    print(f"儲存指標: {len(all_stocks_result)} 檔")


if __name__ == "__main__":
    main()
