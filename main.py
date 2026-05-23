!pip install yfinance pandas ta -q

import yfinance as yf
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD

BOT_TOKEN = "你的Bot Token"
CHAT_ID = "8851496243"

# ===== 股票池 =====

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

# ===== Telegram =====

def send_telegram(message):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message
    })

# ===== 題材分類 =====

def theme_of(ticker):

    if ticker in ["AAOI","LITE","COHR","FN","CIEN","NOK","AXTI"]:
        return "光通訊"

    if ticker in ["MU","WDC","STX","SNDK"]:
        return "HBM"

    if ticker in ["NVDA","AMD","AVGO","MRVL","TSM","ARM"]:
        return "AI晶片"

    if ticker in ["VRT","ETN","PWR","GEV","CEG","SMR"]:
        return "電力"

    if ticker in ["APLD","NBIS","CRWV","DELL","SMCI","ORCL","ONDS"]:
        return "AI基建"

    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return "台股AI"

    return "其他"

# ===== Relative Strength =====

def benchmark_of(ticker):

    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return "0050.TW"

    return "QQQ"

# ===== 掃描 =====

def scan_stock(ticker):

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

    # ===== 技術條件 =====

    above_ma20 = price > ma20.iloc[-1]
    above_ma50 = price > ma50.iloc[-1]

    ma20_up = ma20.iloc[-1] > ma20.iloc[-5]

    volume_ratio = float(volume.iloc[-1] / vol20.iloc[-1])

    volume_ok = volume_ratio >= 1.5

    rsi_value = float(rsi.iloc[-1])

    rsi_ok = 55 <= rsi_value <= 75

    macd_ok = macd.iloc[-1] > macd_signal.iloc[-1]

    # ===== 箱型突破 =====

    breakout_20d = (
        price >= close.rolling(20).max().iloc[-1] * 0.99
    )

    breakout_50d = (
        price >= close.rolling(50).max().iloc[-1] * 0.99
    )

    # ===== 假突破過濾 =====

    not_too_extended = price < ma20.iloc[-1] * 1.10

    candle_range = high.iloc[-1] - low.iloc[-1]

    upper_shadow = high.iloc[-1] - close.iloc[-1]

    if candle_range == 0:
        upper_shadow_ratio = 0
    else:
        upper_shadow_ratio = float(upper_shadow / candle_range)

    no_big_upper_shadow = upper_shadow_ratio < 0.45

    # ===== Relative Strength =====

    stock_return = close.iloc[-1] / close.iloc[-20] - 1

    bm_close = bm["Close"].squeeze()

    bm_return = bm_close.iloc[-1] / bm_close.iloc[-20] - 1

    rs_ok = stock_return > bm_return

    # ===== 分數系統 =====

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

    if theme_of(ticker) != "其他":
        score += 1

    if not not_too_extended:
        score -= 2

    if not no_big_upper_shadow:
        score -= 2

    # ===== 等級 =====

    if score >= 11:
        level = "🔥 強勢突破"

    elif score >= 8:
        level = "⚡ 值得觀察"

    elif score >= 6:
        level = "👀 潛在轉強"

    else:
        return None

    entry = round(price, 2)

    stop = round(entry * 0.93, 2)

    tp1 = round(entry * 1.08, 2)

    tp2 = round(entry * 1.15, 2)

    tp3 = round(entry * 1.25, 2)

    return {
        "ticker": ticker,
        "theme": theme_of(ticker),
        "score": score,
        "level": level,
        "message": f"""
{level}

股票：{ticker}
題材：{theme_of(ticker)}

價格：{entry}

分數：{score}/13

條件：

✅ 站上20MA與50MA
✅ 20MA走升
✅ 放量 {round(volume_ratio,2)}x
✅ RSI：{round(rsi_value,2)}
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
    }

# ===== 主程式 =====

results = []

send_telegram("🚀 v5 Hedge Fund Scanner 啟動")

for i, ticker in enumerate(WATCHLIST, 1):

    try:

        result = scan_stock(ticker)

        if result:
            results.append(result)

    except Exception as e:

        print(ticker, e)

    if i % 10 == 0:
        print(f"已掃描 {i}/{len(WATCHLIST)}")

# ===== 排序 =====

results = sorted(
    results,
    key=lambda x: x["score"],
    reverse=True
)

# ===== 題材統計 =====

theme_count = {}

for r in results:

    theme = r["theme"]

    theme_count[theme] = theme_count.get(theme, 0) + 1

# ===== 發送 =====

if results:

    summary = "📊 今日市場熱度\n\n"

    for k, v in sorted(
        theme_count.items(),
        key=lambda x: x[1],
        reverse=True
    ):

        summary += f"{k}: {v} 檔\n"

    send_telegram(summary)

    send_telegram(
        f"🔥 今日共找到 {len(results)} 檔高分股票"
    )

    for r in results[:10]:

        send_telegram(r["message"])

else:

    send_telegram(
        "今日沒有符合條件的高分技術訊號"
    )

print("v5 掃描完成")