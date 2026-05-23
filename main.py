import time
import requests
import yfinance as yf
import pandas as pd
from position_manager import manage_positions
from datetime import datetime, timedelta

from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange

# =========================
# Telegram
# =========================

BOT_TOKEN = "8846284007:AAEZz4f50N8g1JcC6P8Z2ujcA2hx32-gv5A"
CHAT_ID = "8851496243"

# =========================
# Config
# =========================

SCAN_INTERVAL = 300

MAX_SCAN_PER_ROUND = 300

sent_today = set()

scan_pointer = 0

# =========================
# Theme Keywords
# =========================

THEME_KEYWORDS = {

    "AI基建": [
        "data","cloud","gpu","server",
        "compute","ai","infrastructure"
    ],

    "光通訊": [
        "optical","photonics","laser",
        "fiber","transceiver"
    ],

    "HBM / 記憶體": [
        "memory","dram","storage",
        "flash","ssd"
    ],

    "電力 / 核電": [
        "power","energy","grid",
        "nuclear","utility","electrical"
    ],

    "國防 / 無人機": [
        "defense","drone","military",
        "aerospace","autonomous","radar"
    ],

    "機器人 / 自動化": [
        "robot","automation","humanoid",
        "industrial"
    ],

    "資安": [
        "cyber","security","firewall",
        "endpoint","network security"
    ],

    "太空 / 衛星": [
        "space","satellite","orbital",
        "rocket"
    ],

    "AI生技 / 醫療科技": [
        "biotech","genomics","drug",
        "medical","healthcare"
    ]
}

# =========================
# 時間
# =========================

def now_tw():

    return datetime.utcnow() + timedelta(hours=8)

# =========================
# Telegram
# =========================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": msg
        }
    )

# =========================
# 台股判定
# =========================

def is_tw(ticker):

    return (
        ticker.endswith(".TW")
        or
        ticker.endswith(".TWO")
    )

# =========================
# 市場時間
# =========================

def market_open_for(ticker):

    n = now_tw()

    if n.weekday() >= 5:
        return False

    minutes = n.hour * 60 + n.minute

    if is_tw(ticker):

        return (
            9 * 60
            <=
            minutes
            <=
            13 * 60 + 30
        )

    return (
        minutes >= 21 * 60 + 30
        or
        minutes <= 4 * 60
    )

# =========================
# Benchmark
# =========================

def benchmark_of(ticker):

    if is_tw(ticker):

        return "0050.TW"

    return "QQQ"

# =========================
# 市場風險模式
# =========================

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

        q = qqq["Close"].squeeze()

        s = soxx["Close"].squeeze()

        v = float(
            vix["Close"].squeeze().iloc[-1]
        )

        q_risk = (
            q.iloc[-1]
            <
            q.rolling(20).mean().iloc[-1]
        )

        s_risk = (
            s.iloc[-1]
            <
            s.rolling(20).mean().iloc[-1]
        )

        return (
            q_risk
            or
            s_risk
            or
            v > 25
        )

    except:

        return False

# =========================
# 全市場股票池
# =========================

def get_us_market():

    try:

        url = (
            "https://www.nasdaqtrader.com/"
            "dynamic/SymDir/nasdaqlisted.txt"
        )

        df = pd.read_csv(url, sep="|")

        tickers = df["Symbol"].dropna().tolist()

        tickers = [

            t for t in tickers

            if (
                "$" not in t
                and
                "." not in t
                and
                len(t) <= 5
            )
        ]

        return tickers

    except:

        return []

# =========================
# 探索式 Theme 判定
# =========================

def detect_themes(ticker, info_text):

    hits = []

    text = info_text.lower()

    for theme, keywords in THEME_KEYWORDS.items():

        for kw in keywords:

            if kw in text:

                hits.append(theme)

                break

    if len(hits) == 0:

        hits.append("一般市場股")

    return hits

# =========================
# 股票評分
# =========================

def scan_stock(ticker, risk_mode=False):

    bm_ticker = benchmark_of(ticker)

    try:

        stock = yf.Ticker(ticker)

        info = stock.info

        name = str(info.get("longBusinessSummary", ""))

        themes = detect_themes(ticker, name)

        df = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        bm = yf.download(
            bm_ticker,
            period="6mo",
            interval="1d",
            auto_adjust=True,
            progress=False
        )

        if (
            df.empty
            or
            bm.empty
            or
            len(df) < 80
        ):
            return None

        close = df["Close"].squeeze()

        high = df["High"].squeeze()

        low = df["Low"].squeeze()

        volume = df["Volume"].squeeze()

        price = float(close.iloc[-1])

        # 過濾垃圾股

        if price < 5:

            return None

        avg_volume = volume.rolling(20).mean().iloc[-1]

        if avg_volume < 500000:

            return None

        ma20 = close.rolling(20).mean()

        ma50 = close.rolling(50).mean()

        vol20 = volume.rolling(20).mean()

        volume_ratio = float(
            volume.iloc[-1]
            /
            vol20.iloc[-1]
        )

        rsi = RSIIndicator(close).rsi()

        rsi_value = float(rsi.iloc[-1])

        macd_obj = MACD(close)

        macd = macd_obj.macd()

        macd_signal = macd_obj.macd_signal()

        atr = AverageTrueRange(
            high,
            low,
            close,
            window=14
        ).average_true_range()

        atr_value = float(atr.iloc[-1])

        atr_pct = atr_value / price

        bm_close = bm["Close"].squeeze()

        rs_20d = (
            close.iloc[-1]
            /
            close.iloc[-20]
            - 1
        )

        bm_20d = (
            bm_close.iloc[-1]
            /
            bm_close.iloc[-20]
            - 1
        )

        rs_ok = rs_20d > bm_20d

        breakout_20d = (
            price
            >=
            close.rolling(20).max().iloc[-1] * 0.99
        )

        compression = atr_pct < 0.055

        score = 0

        if price > ma20.iloc[-1]:
            score += 8

        if price > ma50.iloc[-1]:
            score += 8

        if volume_ratio >= 1.5:
            score += 15

        if rs_ok:
            score += 15

        if breakout_20d:
            score += 15

        if 55 <= rsi_value <= 75:
            score += 8

        if macd.iloc[-1] > macd_signal.iloc[-1]:
            score += 8

        if compression:
            score += 6

        if len(themes) >= 2:
            score += 8

        if risk_mode:
            score -= 12

        if score >= 88:

            level = "🔥 A級主攻"

        elif score >= 75:

            level = "⚡ B級觀察"

        elif score >= 65:

            level = "👀 C級早期轉強"

        else:

            return None

        entry = round(price, 2)

        stop = round(
            entry - atr_value * 2,
            2
        )

        tp1 = round(entry * 1.08, 2)

        tp2 = round(entry * 1.15, 2)

        msg = f"""
{level}

股票：{ticker}

Theme：
{", ".join(themes)}

價格：
{entry}

總分：
{score}/100

RS：
{"強於市場" if rs_ok else "弱於市場"}

Volume：
{round(volume_ratio, 2)}x

RSI：
{round(rsi_value, 2)}

ATR%：
{round(atr_pct * 100, 2)}%

20D Breakout：
{"是" if breakout_20d else "否"}

交易計畫：

停損：
{stop}

TP1：
{tp1}

TP2：
{tp2}
"""

        return {
            "ticker": ticker,
            "score": score,
            "themes": themes,
            "message": msg
        }

    except:

        return None

# =========================
# 啟動
# =========================

send_telegram(
    "🚀 v12 Institutional Alpha Engine 已啟動"
)

# =========================
# 主程式
# =========================

market_universe = get_us_market()

while True:

    try:

        today = now_tw().strftime("%Y-%m-%d")

        risk_mode = market_risk_mode()

        # 分批掃描避免 Railway 爆掉

        start = scan_pointer

        end = start + MAX_SCAN_PER_ROUND

        batch = market_universe[start:end]

        scan_pointer = end

        if scan_pointer >= len(market_universe):

            scan_pointer = 0

        # =========================
        # 持倉管理
        # =========================

        position_msgs = manage_positions()

        for msg in position_msgs:
            send_telegram(msg)

        # =========================
        # 市場掃描
        # =========================

        results = []

        for ticker in batch:

            if not market_open_for(ticker):

                continue

            key = f"{today}-{ticker}"

            if key in sent_today:

                continue

            result = scan_stock(
                ticker,
                risk_mode
            )

            if result:

                sent_today.add(key)

                results.append(result)

        results = sorted(
            results,
            key=lambda x: x["score"],
            reverse=True
        )

        # =========================
        # Theme Ranking
        # =========================

        if results:

            theme_count = {}

            for r in results:

                for th in r["themes"]:

                    theme_count[th] = (
                        theme_count.get(th, 0)
                        + 1
                    )

            summary = (
                "📊 Market Discovery 主線\n\n"
            )

            sorted_theme = sorted(
                theme_count.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for theme, count in sorted_theme:

                summary += (
                    f"{theme}: {count} 檔\n"
                )

            if risk_mode:

                summary += (
                    "\n⚠️ 市場風險模式啟動"
                )

            send_telegram(summary)

            send_telegram(
                f"🔥 本輪找到 {len(results)} 檔 Discovery 訊號"
            )

            for r in results[:10]:

                send_telegram(r["message"])

        else:

            print("本輪沒有訊號")

        if len(sent_today) > 1000:

            sent_today.clear()

        time.sleep(SCAN_INTERVAL)

    except Exception as e:

        print("主程式錯誤：", e)

        time.sleep(60)