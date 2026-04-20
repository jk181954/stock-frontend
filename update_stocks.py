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
    """TPEX 民國日期 1150402 → 西元 2026-04-02"""
    date_str = str(date_str).strip()
    if len(date_str) == 7 and date_str.isdigit():
        year = int(date_str[:3]) + 1911
        return f"{year}-{date_str[3:5]}-{date_str[5:7]}"
    return None

def get_last_trading_date_from_twse():
    """TWSE 月曆 API 取得最近真實交易日（防呆）"""
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
    """四層來源：TPEX → MI_INDEX（主力）→ afterTrading 備援 → openapi 最終備援"""
    today_data = {}
    quote_dates = {}
    actual_date = None
    tw_today = datetime.now(tz=pytz.timezone("Asia/Taipei")).strftime("%Y-%m-%d")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # ① TPEX 上櫃（重試機制）
    try:
        tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        tpex_json = None

        for attempt in range(3):
            res = requests.get(tpex_url, headers=headers, timeout=20)
            if res.status_code == 200 and res.text.strip():
                try:
                    tpex_json = res.json()
                    break
                except json.JSONDecodeError:
                    pass
            time.sleep(2 * (attempt + 1))

        if tpex_json:
            count = 0
            latest_tpex = None
            for item in tpex_json:
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
                    if parsed and (latest_tpex is None or parsed > latest_tpex):
                        latest_tpex = parsed
                    count += 1
            print(f"TPEX: {count} 檔（日期: {latest_tpex}）")
        else:
            print("TPEX API 暫不可用")
    except Exception as e:
        print(f"TPEX 行情失敗: {e}")

    # ② TWSE MI_INDEX 每日收盤行情（主力，一次抓全部 ~1350 檔，含正確日期）
    twse_ok = False
    try:
        date_nodash = tw_today.replace("-", "")
        mi_url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                  f"?date={date_nodash}&type=ALLBUT0999&response=json")
        res = requests.get(mi_url, headers=headers, timeout=20)
        data = res.json()
        if data.get("stat") != "OK":
            raise ValueError(f"MI_INDEX stat={data.get('stat')}")

        raw_date = data.get("date", "").strip()
        parsed_mi = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                     if len(raw_date) == 8 else None)

        count = 0
        for table in data.get("tables", []):
            if "每日收盤行情" not in str(table.get("title", "")):
                continue
            for row in table.get("data", []):
                if len(row) < 9:
                    continue
                code = str(row[0]).strip()
                close_raw = str(row[8]).replace(",", "").strip()   # col[8] = 收盤價
                vol_raw   = str(row[2]).replace(",", "").strip()   # col[2] = 成交股數
                if len(code) == 4 and close_raw.replace(".", "", 1).isdigit() and vol_raw.isdigit():
                    today_data[code] = {"close": float(close_raw), "volume": float(vol_raw) / 1000}
                    quote_dates[code] = parsed_mi
                    count += 1

        if parsed_mi and (actual_date is None or parsed_mi > actual_date):
            actual_date = parsed_mi
        print(f"TWSE MI_INDEX: {count} 檔（日期: {parsed_mi}）")
        twse_ok = True
    except Exception as e:
        print(f"TWSE MI_INDEX 失敗: {e}，改用備援...")

    if not twse_ok:
        # ③ TWSE afterTrading STOCK_DAY_ALL 備援
        try:
            date_nodash = tw_today.replace("-", "")
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json&date={date_nodash}"
            res = requests.get(url, headers=headers, timeout=20)
            data = res.json()
            if data.get("stat") == "OK":
                raw_date = data.get("date", "").strip()
                parsed_twse = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                               if len(raw_date) == 8 else actual_date)
                count = 0
                for row in data.get("data", []):
                    if len(row) < 8:
                        continue
                    code = str(row[0]).strip()
                    close_raw = str(row[7]).replace(",", "").strip()
                    vol_raw   = str(row[2]).replace(",", "").strip()
                    if len(code) == 4 and close_raw.replace(".", "", 1).isdigit() and vol_raw.isdigit():
                        today_data[code] = {"close": float(close_raw), "volume": float(vol_raw) / 1000}
                        quote_dates[code] = parsed_twse
                        count += 1
                if parsed_twse and (actual_date is None or parsed_twse > actual_date):
                    actual_date = parsed_twse
                print(f"TWSE afterTrading 備援: {count} 檔（日期: {parsed_twse}）")
                twse_ok = True
            else:
                raise ValueError(f"afterTrading stat={data.get('stat')}")
        except Exception as e2:
            # ④ TWSE openapi 最終備援
            try:
                res = requests.get(
                    "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                    headers=headers, timeout=15)
                count = 0
                for item in res.json():
                    code = str(item.get("Code", "")).strip()
                    close = str(item.get("ClosingPrice", "")).replace(",", "")
                    vol   = str(item.get("TradeVolume", "")).replace(",", "")
                    date_str = str(item.get("Date", "")).strip()
                    if close and vol and close.replace(".", "", 1).isdigit() and len(code) == 4:
                        parsed = parse_tpex_date(date_str)
                        today_data[code] = {"close": float(close), "volume": float(vol) / 1000}
                        quote_dates[code] = parsed
                        if parsed and (actual_date is None or parsed > actual_date):
                            actual_date = parsed
                        count += 1
                print(f"TWSE openapi 最終備援: {count} 檔")
            except Exception as e3:
                print(f"TWSE 所有備援失敗: {e3}")

    if actual_date is None:
        actual_date = tw_today
        print(f"⚠️ 所有 API 都失敗，使用程式執行日: {actual_date}")

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


def fetch_finmind(code, start_date, end_date, token=""):
    params = {"dataset": "TaiwanStockPrice", "data_id": code,
              "start_date": start_date, "end_date": end_date}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        res = requests.get(FINMIND_API_URL, params=params, headers=headers, timeout=20)
        data = res.json()
        if data.get("status") == 402:
            return "RATE_LIMIT"
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
        print("✅ FinMind：無需補齊。")
        return db

    print(f"⚙️  FinMind 補齊：{len(stale)} 檔...")
    filled = 0
    sleep_sec = 6 if token else 12

    for i, code in enumerate(stale):
        last_date = db[code]["history"][-1]["date"]
        start_dt = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = fetch_finmind(code, start_dt, actual_data_date, token=token)

        if rows == "RATE_LIMIT":
            print(f"⚠️  FinMind 達到請求上限，剩餘 {len(stale)-i} 檔未補，明日繼續。")
            break

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

    print(f"✅ FinMind 完成：補齊 {filled} 檔")
    return db


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


def main():
    print("=== 開始每日極速增量更新 ===")

    if not os.path.exists(DB_FILE):
        print(f"找不到 {DB_FILE}！")
        return

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    today_quotes, quote_dates, actual_data_date = get_today_quotes()
    if not today_quotes or actual_data_date is None:
        print("今日無資料或非交易日，結束。")
        return

    print(f"實際交易日期: {actual_data_date}")

    # 清除重複寫入的錯誤資料
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

    # 寫入 TPEX/TWSE 資料（用 API 日期判斷）
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

    # FinMind 補缺仍落後的股票
    finmind_token = os.environ.get("FINMIND_TOKEN", "")
    still_stale = sum(1 for info in db.values()
                      if info.get("history") and info["history"][-1]["date"] < actual_data_date)
    if still_stale:
        if finmind_token:
            db = backfill_finmind(db, actual_data_date, token=finmind_token)
        else:
            print(f"未設定 FINMIND_TOKEN，{still_stale} 檔無法補齊。")

    # 計算技術指標
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

    # 儲存
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
