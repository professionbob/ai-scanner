import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange

BOT_TOKEN = "8846284007:AAEZz4f50N8g1JcC6P8Z2ujcA2hx32-gv5A"
CHAT_ID = "8851496243"

SCAN_INTERVAL = 300
MAX_SCAN_PER_ROUND = 180
sent_today = set()
signal_history = []

CORE_US = [
    "AAOI","LITE","COHR","FN","CIEN","NOK","AXTI",
    "MU","WDC","STX","SNDK",
    "NVDA","AMD","AVGO","MRVL","TSM","ARM",
    "VRT","ETN","PWR","GEV","CEG","SMR",
    "APLD","NBIS","CRWV","DELL","SMCI","ORCL","ONDS",
    "AMKR","ONTO","MKSI","KLAC","LRCX","AMAT","ASML",
    "ANET","PANW","PLTR","SNOW","NOW"
]

CORE_TW = [
    "2330.TW","3037.TW","2308.TW","6669.TW",
    "2382.TW","3231.TW","2356.TW","3017.TW",
    "3324.TWO","3653.TW","3711.TW","3443.TW",
    "2379.TW","6789.TW","6533.TW","3013.TW",
    "2368.TW","5274.TW","4938.TW","8069.TWO"
]

def now_tw():
    return datetime.utcnow() + timedelta(hours=8)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def is_tw(ticker):
    return ticker.endswith(".TW") or ticker.endswith(".TWO")

def market_open_for(ticker):
    n = now_tw()
    if n.weekday() >= 5:
        return False

    minutes = n.hour * 60 + n.minute

    if is_tw(ticker):
        return 9 * 60 <= minutes <= 13 * 60 + 30

    return minutes >= 21 * 60 + 30 or minutes <= 4 * 60

def theme_of(ticker):
    if ticker in ["AAOI","LITE","COHR","FN","CIEN","NOK","AXTI"]:
        return "光通訊"
    if ticker in ["MU","WDC","STX","SNDK"]:
        return "HBM / 記憶體"
    if ticker in ["NVDA","AMD","AVGO","MRVL","TSM","ARM"]:
        return "AI晶片"
    if ticker in ["VRT","ETN","PWR","GEV","CEG","SMR"]:
        return "電力 / 核電"
    if ticker in ["APLD","NBIS","CRWV","DELL","SMCI","ORCL","ONDS"]:
        return "AI基建"
    if ticker in ["AMKR","ONTO","MKSI","KLAC","LRCX","AMAT","ASML"]:
        return "先進封裝"
    if ticker in ["ANET","PANW","PLTR","SNOW","NOW"]:
        return "AI軟體"
    if is_tw(ticker):
        return "台股AI供應鏈"
    return "一般市場股"

def benchmark_of(ticker):
    return "0050.TW" if is_tw(ticker) else "QQQ"

def get_us_universe():
    try:
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
        df = pd.read_csv(url, sep="|")
        tickers = df["Symbol"].dropna().tolist()
        tickers = [t for t in tickers if "$" not in t and "." not in t]
        return tickers[:1200]
    except:
        return []

def get_tw_universe():
    return CORE_TW

def build_watchlist():
    us = get_us_universe()
    tw = get_tw_universe()
    universe = list(set(CORE_US + CORE_TW + us + tw))
    return universe[:MAX_SCAN_PER_ROUND]

def market_risk_mode():
    try:
        qqq = yf.download("QQQ", period="3mo", interval="1d", progress=False, auto_adjust=True)
        soxx = yf.download("SOXX", period="3mo", interval="1d", progress=False, auto_adjust=True)
        vix = yf.download("^VIX", period="1mo", interval="1d", progress=False, auto_adjust=True)

        q = qqq["Close"].squeeze()
        s = soxx["Close"].squeeze()
        v = float(vix["Close"].squeeze().iloc[-1])

        q_risk = q.iloc[-1] < q.rolling(20).mean().iloc[-1]
        s_risk = s.iloc[-1] < s.rolling(20).mean().iloc[-1]

        return q_risk or s_risk or v > 25
    except:
        return False

def scan_stock(ticker, risk_mode=False):
    bm_ticker = benchmark_of(ticker)

    df = yf.download(ticker, period="6mo", interval="1d", auto_adjust=True, progress=False)
    bm = yf.download(bm_ticker, period="6mo", interval="1d", auto_adjust=True, progress=False)

    if df.empty or bm.empty or len(df) < 80 or len(bm) < 80:
        return None

    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    price = float(close.iloc[-1])

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    vol20 = volume.rolling(20).mean()
    volume_ratio = float(volume.iloc[-1] / vol20.iloc[-1])

    rsi = RSIIndicator(close).rsi()
    rsi_value = float(rsi.iloc[-1])

    macd_obj = MACD(close)
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()

    atr = AverageTrueRange(high, low, close, window=14).average_true_range()
    atr_pct = float(atr.iloc[-1] / price)

    bm_close = bm["Close"].squeeze()
    rs_20d = close.iloc[-1] / close.iloc[-20] - 1
    bm_20d = bm_close.iloc[-1] / bm_close.iloc[-20] - 1
    rs_ok = rs_20d > bm_20d

    above_ma20 = price > ma20.iloc[-1]
    above_ma50 = price > ma50.iloc[-1]
    ma20_up = ma20.iloc[-1] > ma20.iloc[-5]

    breakout_20d = price >= close.rolling(20).max().iloc[-1] * 0.99
    breakout_50d = price >= close.rolling(50).max().iloc[-1] * 0.99

    compression = atr_pct < 0.055
    tight_range = (high.iloc[-5:].max() - low.iloc[-5:].min()) / price < 0.08

    pullback_ok = price > ma20.iloc[-1] and price < close.rolling(20).max().iloc[-1] * 0.96
    mean_reversion = rsi_value < 40 and price > ma5.iloc[-1]

    candle_range = high.iloc[-1] - low.iloc[-1]
    upper_shadow_ratio = 0 if candle_range == 0 else float((high.iloc[-1] - close.iloc[-1]) / candle_range)
    no_fake_breakout = upper_shadow_ratio < 0.45 and price < ma20.iloc[-1] * 1.12

    theme = theme_of(ticker)

    score = 0
    if above_ma20: score += 8
    if above_ma50: score += 8
    if ma20_up: score += 8
    if volume_ratio >= 1.5: score += 15
    if 55 <= rsi_value <= 75: score += 8
    if macd.iloc[-1] > macd_signal.iloc[-1]: score += 8
    if breakout_20d: score += 12
    if breakout_50d: score += 12
    if rs_ok: score += 15
    if compression: score += 6
    if tight_range: score += 6
    if theme in ["光通訊","HBM / 記憶體","AI基建","AI晶片","先進封裝","電力 / 核電"]: score += 12
    if not no_fake_breakout: score -= 15
    if risk_mode: score -= 12

    strategies = []
    if breakout_20d or breakout_50d:
        strategies.append("Breakout")
    if compression and tight_range:
        strategies.append("Volatility Compression")
    if pullback_ok:
        strategies.append("Pullback Setup")
    if mean_reversion:
        strategies.append("Mean Reversion")

    if score >= 85:
        level = "🔥 A級主攻"
    elif score >= 72:
        level = "⚡ B級觀察"
    elif score >= 62:
        level = "👀 C級早期轉強"
    else:
        return None

    entry = round(price, 2)
    stop = round(entry - float(atr.iloc[-1]) * 2, 2)
    tp1 = round(entry * 1.08, 2)
    tp2 = round(entry * 1.15, 2)
    tp3 = round(entry * 1.25, 2)

    msg = f"""
{level}

股票：{ticker}
題材：{theme}
策略：{", ".join(strategies) if strategies else "Trend / RS"}
價格：{entry}
總分：{score}/100

核心條件：
RS強於 {bm_ticker}：{"是" if rs_ok else "否"}
放量倍數：{round(volume_ratio, 2)}x
RSI：{round(rsi_value, 2)}
ATR%：{round(atr_pct * 100, 2)}%
20D突破：{"是" if breakout_20d else "否"}
50D突破：{"是" if breakout_50d else "否"}
假突破過濾：{"通過" if no_fake_breakout else "未通過"}

交易計畫：
觀察區：{entry}
ATR停損：{stop}
TP1：{tp1}
TP2：{tp2}
TP3：{tp3}

提醒：
這是系統訊號，不代表直接追高。
若跌回20MA或放量後無法續強，要小心假突破。
"""

    return {
        "ticker": ticker,
        "score": score,
        "theme": theme,
        "message": msg
    }

def record_signal(result):
    signal_history.append({
        "date": now_tw().strftime("%Y-%m-%d %H:%M"),
        "ticker": result["ticker"],
        "score": result["score"],
        "theme": result["theme"]
    })

send_telegram("🚀 v8 AI Multi-Strategy Scanner 已啟動")

while True:
    try:
        today = now_tw().strftime("%Y-%m-%d")
        watchlist = build_watchlist()
        active = [t for t in watchlist if market_open_for(t)]

        if not active:
            print("目前非開盤時間")
            time.sleep(SCAN_INTERVAL)
            continue

        risk_mode = market_risk_mode()
        results = []

        for ticker in active:
            key = f"{today}-{ticker}"
            if key in sent_today:
                continue

            try:
                result = scan_stock(ticker, risk_mode)
                if result:
                    sent_today.add(key)
                    record_signal(result)
                    results.append(result)
            except Exception as e:
                print(ticker, e)

        results = sorted(results, key=lambda x: x["score"], reverse=True)

        if results:
            theme_count = {}
            for r in results:
                theme_count[r["theme"]] = theme_count.get(r["theme"], 0) + 1

            summary = "📊 本輪市場主線\n\n"
            for theme, count in sorted(theme_count.items(), key=lambda x: x[1], reverse=True):
                summary += f"{theme}: {count} 檔\n"

            if risk_mode:
                summary += "\n⚠️ 市場風險模式啟動，系統已自動提高門檻。"

            send_telegram(summary)
            send_telegram(f"🔥 本輪找到 {len(results)} 檔高分股票")

            for r in results[:10]:
                send_telegram(r["message"])
        else:
            print("本輪沒有高分訊號")

        if len(sent_today) > 500:
            sent_today.clear()

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print("主程式錯誤：", e)
        time.sleep(60)