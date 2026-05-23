import time
import requests
import yfinance as yf
import time
import requests
import yfinance as yf
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD

# ===== Telegram =====

BOT_TOKEN = "8846284007:AAEZz4f50N8g1JcC6P8Z2ujcA2hx32-gv5A"
CHAT_ID = "8851496243"

# ===== 設定 =====

SCAN_INTERVAL = 300
sent_today = set()

# ===== 台股 AI =====

TAIWAN_AI = [
    "2330.TW","3037.TW","2308.TW","6669.TW",
    "2382.TW","3231.TW","2356.TW","3017.TW",
    "3324.TWO","3653.TW","3711.TW","3443.TW",
    "2379.TW","6789.TW","6533.TW","3013.TW",
    "2368.TW","5274.TW","4938.TW","8069.TWO"
]

# ===== 美股 AI =====

AI_THEME = [
    "AAOI","LITE","COHR","FN","CIEN","NOK",
    "MU","WDC","STX","SNDK",
    "NVDA","AMD","AVGO","MRVL","TSM","ARM",
    "VRT","ETN","PWR","GEV","CEG","SMR",
    "APLD","NBIS","CRWV","DELL","SMCI","ORCL",
    "ONDS","AXTI","AMKR","ONTO","MKSI",
    "KLAC","LRCX","AMAT","ASML","TSLA",
    "ANET","PANW","PLTR","SNOW","NOW"
]

WATCHLIST = list(set(TAIWAN_AI + AI_THEME))

# ===== 時間 =====

def now_tw():
    return datetime.utcnow() + timedelta(hours=8)

# ===== Telegram =====

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        }
    )

# ===== 市場判定 =====

def is_taiwan_stock(ticker):
    return ticker.endswith(".TW") or ticker.endswith(".TWO")

def market_open_for(ticker):
    now = now_tw()

    if now.weekday() >= 5:
        return False

    hour = now.hour
    minute = now.minute
    current = hour * 60 + minute

    # 台股
    if is_taiwan_stock(ticker):
        return 9 * 60 <= current <= 13 * 60 + 30

    # 美股
    return current >= 21 * 60 + 30 or current <= 4 * 60

# ===== 題材分類 =====

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

    if is_taiwan_stock(ticker):
        return "台股AI供應鏈"

    return "其他"

# ===== Benchmark =====

def benchmark_of(ticker):

    if is_taiwan_stock(ticker):
        return "0050.TW"

    return "QQQ"

# ===== 市場風險模式 =====

def market_risk_mode():

    try:

        qqq = yf.download(
            "QQQ",
            period="3mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        soxx = yf.download(
            "SOXX",
            period="3mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        vix = yf.download(
            "^VIX",
            period="1mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        qqq_close = qqq["Close"].squeeze()
        soxx_close = soxx["Close"].squeeze()
        vix_now = float(vix["Close"].squeeze().iloc[-1])

        qqq_risk = (
            qqq_close.iloc[-1]
            <
            qqq_close.rolling(20).mean().iloc[-1]
        )

        soxx_risk = (
            soxx_close.iloc[-1]
            <
            soxx_close.rolling(20).mean().iloc[-1]
        )

        return qqq_risk or soxx_risk or vix_now > 25

    except:
        return False

# ===== 掃描股票 =====

def scan_stock(ticker, risk_mode=False):

    benchmark = benchmark_of(ticker)

    df = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    bm = yf.download(
        benchmark,
        period="6mo",
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    if df.empty or bm.empty or len(df) < 60:
        return None

    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    # ===== 均線 =====

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    # ===== 成交量 =====

    vol20 = volume.rolling(20).mean()
    volume_ratio = float(volume.iloc[-1] / vol20.iloc[-1])

    # ===== RSI =====

    rsi = RSIIndicator(close).rsi()
    rsi_value = float(rsi.iloc[-1])

    # ===== MACD =====

    macd_obj = MACD(close)

    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()

    # ===== 價格 =====

    price = float(close.iloc[-1])

    # ===== Relative Strength =====

    stock_return = (
        close.iloc[-1] / close.iloc[-20] - 1
    )

    bm_close = bm["Close"].squeeze()

    bm_return = (
        bm_close.iloc[-1] / bm_close.iloc[-20] - 1
    )

    rs_ok = stock_return > bm_return

    # ===== Breakout =====

    breakout_20d = (
        price >= close.rolling(20).max().iloc[-1] * 0.99
    )

    breakout_50d = (
        price >= close.rolling(50).max().iloc[-1] * 0.99
    )

    # ===== 趨勢 =====

    above_ma20 = price > ma20.iloc[-1]
    above_ma50 = price > ma50.iloc[-1]

    ma20_up = (
        ma20.iloc[-1] > ma20.iloc[-5]
    )

    # ===== Volume Expansion =====

    volume_ok = volume_ratio >= 1.5

    # ===== RSI =====

    rsi_ok = (
        55 <= rsi_value <= 75
    )

    # ===== MACD =====

    macd_ok = (
        macd.iloc[-1] > macd_signal.iloc[-1]
    )

    # ===== 避免過熱 =====

    not_too_extended = (
        price < ma20.iloc[-1] * 1.10
    )

    # ===== 假突破過濾 =====

    candle_range = high.iloc[-1] - low.iloc[-1]

    if candle_range == 0:
        upper_shadow_ratio = 0
    else:
        upper_shadow_ratio = (
            high.iloc[-1] - close.iloc[-1]
        ) / candle_range

    no_big_upper_shadow = upper_shadow_ratio < 0.45

    # ===== 評分 =====

    score = 0

    # Trend
    if above_ma20:
        score += 1

    if above_ma50:
        score += 1

    if ma20_up:
        score += 1

    # Volume
    if volume_ok:
        score += 2

    # RSI
    if rsi_ok:
        score += 1

    # MACD
    if macd_ok:
        score += 1

    # Breakout
    if breakout_20d:
        score += 2

    if breakout_50d:
        score += 2

    # Relative Strength
    if rs_ok:
        score += 2

    # 題材加權
    theme = theme_of(ticker)

    if theme in [
        "光通訊",
        "HBM / 記憶體",
        "AI基建",
        "AI晶片",
        "先進封裝"
    ]:
        score += 2

    # 過熱扣分
    if not not_too_extended:
        score -= 2

    # 假突破扣分
    if not no_big_upper_shadow:
        score -= 2

    # 市場風險模式
    if risk_mode:
        score -= 2

    # ===== 分級 =====

    if score >= 12:
        level = "🔥 A級強勢突破"

    elif score >= 9:
        level = "⚡ B級值得觀察"

    elif score >= 7:
        level = "👀 C級潛在轉強"

    else:
        return None

    # ===== 交易計畫 =====

    entry = round(price, 2)

    stop = round(entry * 0.93, 2)

    tp1 = round(entry * 1.08, 2)
    tp2 = round(entry * 1.15, 2)
    tp3 = round(entry * 1.25, 2)

    # ===== 訊息 =====

    msg = f"""
{level}

股票：{ticker}
題材：{theme}
價格：{entry}

分數：{score}/15

條件：

✅ 站上20MA與50MA
✅ 20MA走升
✅ 放量 {round(volume_ratio, 2)}x
✅ RSI：{round(rsi_value, 2)}
✅ MACD偏多
✅ Relative Strength 強於 {benchmark}
✅ 箱型突破
✅ 假突破過濾

停損：{stop}

停利：
TP1：{tp1}
TP2：{tp2}
TP3：{tp3}
"""

    return {
        "ticker": ticker,
        "score": score,
        "message": msg,
        "theme": theme
    }

# ===== 啟動 =====

send_telegram("🚀 v7 AI Multi-Factor Scanner 已啟動")

# ===== 主迴圈 =====

while True:

    try:

        today = now_tw().strftime("%Y-%m-%d")

        active_watchlist = []

        for t in WATCHLIST:

            if market_open_for(t):
                active_watchlist.append(t)

        if len(active_watchlist) == 0:

            print("目前非開盤時間")

            time.sleep(SCAN_INTERVAL)

            continue

        risk_mode = market_risk_mode()

        results = []

        for ticker in active_watchlist:

            key = f"{today}-{ticker}"

            if key in sent_today:
                continue

            try:

                result = scan_stock(
                    ticker,
                    risk_mode=risk_mode
                )

                if result:

                    sent_today.add(key)

                    results.append(result)

            except Exception as e:

                print(ticker, e)

        # ===== 排序 =====

        results = sorted(
            results,
            key=lambda x: x["score"],
            reverse=True
        )

        # ===== 市場主線 =====

        if results:

            theme_count = {}

            for r in results:

                th = r["theme"]

                if th not in theme_count:
                    theme_count[th] = 0

                theme_count[th] += 1

            summary = "📊 今日市場主線\n\n"

            sorted_theme = sorted(
                theme_count.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for theme, count in sorted_theme:

                summary += f"{theme}: {count} 檔\n"

            if risk_mode:

                summary += (
                    "\n⚠️ 市場風險模式開啟"
                    "\nQQQ/SOXX轉弱或VIX偏高"
                )

            send_telegram(summary)

            send_telegram(
                f"🔥 本輪找到 {len(results)} 檔高分股票"
            )

            # ===== 只發前10檔 =====

            for r in results[:10]:

                send_telegram(r["message"])

        else:

            print("本輪沒有高分股票")

        # ===== 清理 =====

        if len(sent_today) > 300:
            sent_today.clear()

        # ===== 等待 =====

        time.sleep(SCAN_INTERVAL)

    except Exception as e:

        print("主程式錯誤：", e)

        time.sleep(60)
from ta.momentum import RSIIndicator
from ta.trend import MACD

BOT_TOKEN = "8846284007:AAEZz4f50N8g1JcC6P8Z2ujcA2hx32-gv5A"
CHAT_ID = "8851496243"

SCAN_INTERVAL = 300
sent_today = set()

TAIWAN_AI = [
    "2330.TW","3037.TW","2308.TW","6669.TW",
    "2382.TW","3231.TW","2356.TW","3017.TW",
    "3324.TWO","3653.TW","3711.TW","3443.TW"
]

AI_THEME = [
    "AAOI","LITE","COHR","FN","CIEN","NOK",
    "MU","WDC","STX","SNDK",
    "NVDA","AMD","AVGO","MRVL","TSM","ARM",
    "VRT","ETN","PWR","GEV","CEG","SMR",
    "APLD","NBIS","CRWV","DELL","SMCI","ORCL",
    "ONDS","AXTI"
]

WATCHLIST = list(set(TAIWAN_AI + AI_THEME))

def now_tw():
    return datetime.utcnow() + timedelta(hours=8)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

def is_taiwan_stock(ticker):
    return ticker.endswith(".TW") or ticker.endswith(".TWO")

def market_open_for(ticker):
    now = now_tw()
    if now.weekday() >= 5:
        return False

    hour = now.hour
    minute = now.minute
    current = hour * 60 + minute

    if is_taiwan_stock(ticker):
        return 9 * 60 <= current <= 13 * 60 + 30

    return current >= 21 * 60 + 30 or current <= 4 * 60

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
    if is_taiwan_stock(ticker):
        return "台股AI供應鏈"
    return "其他"

def benchmark_of(ticker):
    return "0050.TW" if is_taiwan_stock(ticker) else "QQQ"

def market_risk_mode():
    try:
        qqq = yf.download("QQQ", period="3mo", interval="1d", progress=False, auto_adjust=True)
        soxx = yf.download("SOXX", period="3mo", interval="1d", progress=False, auto_adjust=True)
        vix = yf.download("^VIX", period="1mo", interval="1d", progress=False, auto_adjust=True)

        qqq_close = qqq["Close"].squeeze()
        soxx_close = soxx["Close"].squeeze()
        vix_now = float(vix["Close"].squeeze().iloc[-1])

        qqq_risk = qqq_close.iloc[-1] < qqq_close.rolling(20).mean().iloc[-1]
        soxx_risk = soxx_close.iloc[-1] < soxx_close.rolling(20).mean().iloc[-1]

        return qqq_risk or soxx_risk or vix_now > 25
    except:
        return False

def scan_stock(ticker, risk_mode=False):
    benchmark = benchmark_of(ticker)

    df = yf.download(ticker, period="6mo", interval="1d", auto_adjust=True, progress=False)
    bm = yf.download(benchmark, period="6mo", interval="1d", auto_adjust=True, progress=False)

    if df.empty or bm.empty or len(df) < 60 or len(bm) < 60:
        return None

    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    vol20 = volume.rolling(20).mean()

    rsi = RSIIndicator(close).rsi()
    macd_obj = MACD(close)
    macd = macd_obj.macd()
    macd_signal = macd_obj.macd_signal()

    price = float(close.iloc[-1])
    volume_ratio = float(volume.iloc[-1] / vol20.iloc[-1])
    rsi_value = float(rsi.iloc[-1])

    above_ma20 = price > ma20.iloc[-1]
    above_ma50 = price > ma50.iloc[-1]
    ma20_up = ma20.iloc[-1] > ma20.iloc[-5]
    volume_ok = volume_ratio >= 1.5
    rsi_ok = 55 <= rsi_value <= 75
    macd_ok = macd.iloc[-1] > macd_signal.iloc[-1]

    breakout_20d = price >= close.rolling(20).max().iloc[-1] * 0.99
    breakout_50d = price >= close.rolling(50).max().iloc[-1] * 0.99

    not_too_extended = price < ma20.iloc[-1] * 1.10

    candle_range = high.iloc[-1] - low.iloc[-1]
    upper_shadow_ratio = 0 if candle_range == 0 else float((high.iloc[-1] - close.iloc[-1]) / candle_range)
    no_big_upper_shadow = upper_shadow_ratio < 0.45

    stock_return = close.iloc[-1] / close.iloc[-20] - 1
    bm_close = bm["Close"].squeeze()
    bm_return = bm_close.iloc[-1] / bm_close.iloc[-20] - 1
    rs_ok = stock_return > bm_return

    score = 0
    if above_ma20: score += 1
    if above_ma50: score += 1
    if ma20_up: score += 1
    if volume_ok: score += 2
    if rsi_ok: score += 1
    if macd_ok: score += 1
    if breakout_20d: score += 2
    if breakout_50d: score += 2
    if rs_ok: score += 2
    if theme_of(ticker) != "其他": score += 1
    if not not_too_extended: score -= 2
    if not no_big_upper_shadow: score -= 2
    if risk_mode: score -= 2

    if score >= 12:
        level = "🔥 A級強勢突破"
    elif score >= 9:
        level = "⚡ B級值得觀察"
    elif score >= 7:
        level = "👀 C級潛在轉強"
    else:
        return None

    entry = round(price, 2)
    stop = round(entry * 0.93, 2)
    tp1 = round(entry * 1.08, 2)
    tp2 = round(entry * 1.15, 2)
    tp3 = round(entry * 1.25, 2)

    msg = f"""
{level}

股票：{ticker}
題材：{theme_of(ticker)}
價格：{entry}
分數：{score}/13

條件：
✅ 站上20MA與50MA
✅ 20MA走升
✅ 放量 {round(volume_ratio, 2)}x
✅ RSI：{round(rsi_value, 2)}
✅ MACD偏多
✅ 相對強度優於 {benchmark}
✅ 箱型突破檢查
✅ 假突破過濾

交易計畫：
觀察區：{entry}
停損：{stop}
TP1：{tp1}
TP2：{tp2}
TP3：{tp3}

提醒：
這是技術訊號，不代表直接追高。
若跌回20MA或放量後無法續強，要小心假突破。
"""

    return {"ticker": ticker, "theme": theme_of(ticker), "score": score, "message": msg}

send_telegram("🚀 v6 Institutional AI Scanner 已啟動")

while True:
    try:
        today = now_tw().strftime("%Y-%m-%d")

        active_watchlist = [t for t in WATCHLIST if market_open_for(t)]

        if not active_watchlist:
            print("目前非台股/美股開盤時間")
            time.sleep(SCAN_INTERVAL)
            continue

        risk_mode = market_risk_mode()
        results = []

        for ticker in active_watchlist:
            key = f"{today}-{ticker}"

            if key in sent_today:
                continue

            try:
                result = scan_stock(ticker, risk_mode=risk_mode)

                if result:
                    sent_today.add(key)
                    results.append(result)

            except Exception as e:
                print(ticker, e)

        results = sorted(results, key=lambda x: x["score"], reverse=True)

        if results:
            theme_count = {}
            for r in results:
                theme_count[r["theme"]] = theme_count.get(r["theme"], 0) + 1

            summary = "📊 今日市場主線\n\n"
            for theme, count in sorted(theme_count.items(), key=lambda x: x[1], reverse=True):
                summary += f"{theme}: {count} 檔\n"

            if risk_mode:
                summary += "\n⚠️ 市場風險模式：QQQ/SOXX轉弱或VIX偏高，已提高門檻。"

            send_telegram(summary)
            send_telegram(f"🔥 本輪找到 {len(results)} 檔高分股票")

            for r in results[:10]:
                send_telegram(r["message"])

        else:
            print("本輪無高分訊號")

        if len(sent_today) > 300:
            sent_today.clear()

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print("主程式錯誤：", e)
        time.sleep(60)