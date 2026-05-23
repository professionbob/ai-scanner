import time
import requests
import yfinance as yf

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
# 基本設定
# =========================

SCAN_INTERVAL = 300
MAX_SCAN_PER_ROUND = 220

sent_today = set()

# =========================
# Theme Database
# =========================

THEMES = {

    "AI基建": [
        "NVDA","AMD","AVGO","MRVL","TSM","ARM",
        "APLD","NBIS","CRWV","DELL","SMCI",
        "ORCL","ANET","VRT","ONDS"
    ],

    "光通訊": [
        "AAOI","LITE","COHR","FN","CIEN",
        "NOK","AXTI"
    ],

    "HBM / 記憶體": [
        "MU","WDC","STX","SNDK"
    ],

    "電力 / 核電": [
        "VRT","ETN","PWR","GEV","CEG",
        "SMR","CCJ","BWXT"
    ],

    "先進封裝": [
        "AMKR","ONTO","MKSI","KLAC",
        "LRCX","AMAT","ASML","TSM"
    ],

    "國防 / 無人機": [
        "ONDS","PLTR","KTOS","AVAV",
        "LMT","NOC","RTX","GD","TXT",
        "RKLB"
    ],

    "機器人 / 自動化": [
        "TSLA","TER","SYM",
        "ROK","ISRG","ABBNY","FANUY"
    ],

    "資安": [
        "PANW","CRWD","ZS",
        "FTNT","NET","OKTA"
    ],

    "AI軟體": [
        "PLTR","SNOW","NOW",
        "DDOG","MDB","AI","CRM"
    ],

    "太空 / 衛星": [
        "RKLB","ASTS","IRDM",
        "PL","LUNR"
    ],

    "AI生技 / 醫療科技": [
        "RXRX","SDGR","ILMN",
        "TMO","ISRG","EXAS"
    ],

    "新能源 / 儲能 / 鈾": [
        "CCJ","UUUU","NXE",
        "ENPH","FSLR","FLNC","TSLA"
    ],

    "台股AI供應鏈": [
        "2330.TW","3037.TW","2308.TW",
        "6669.TW","2382.TW","3231.TW",
        "2356.TW","3017.TW","3324.TWO",
        "3653.TW","3711.TW","3443.TW",
        "2379.TW","6789.TW","6533.TW",
        "3013.TW","2368.TW","5274.TW",
        "4938.TW","8069.TWO"
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
# 市場判定
# =========================

def is_tw(ticker):

    return (
        ticker.endswith(".TW")
        or
        ticker.endswith(".TWO")
    )

def market_open_for(ticker):

    n = now_tw()

    if n.weekday() >= 5:
        return False

    minutes = n.hour * 60 + n.minute

    # 台股
    if is_tw(ticker):

        return (
            9 * 60
            <=
            minutes
            <=
            13 * 60 + 30
        )

    # 美股
    return (
        minutes >= 21 * 60 + 30
        or
        minutes <= 4 * 60
    )

# =========================
# Theme 判定
# =========================

def themes_of(ticker):

    hits = []

    for theme, tickers in THEMES.items():

        if ticker in tickers:

            hits.append(theme)

    if len(hits) == 0:

        return ["一般市場股"]

    return hits

# =========================
# Benchmark
# =========================

def benchmark_of(ticker):

    if is_tw(ticker):

        return "0050.TW"

    return "QQQ"

# =========================
# 建立 Watchlist
# =========================

def build_watchlist():

    all_tickers = []

    for tickers in THEMES.values():

        all_tickers.extend(tickers)

    # 去重
    all_tickers = list(dict.fromkeys(all_tickers))

    return all_tickers[:MAX_SCAN_PER_ROUND]

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
# Theme 加權
# =========================

def theme_bonus(theme_list):

    priority = {

        "AI基建": 12,

        "光通訊": 12,

        "HBM / 記憶體": 12,

        "電力 / 核電": 11,

        "先進封裝": 11,

        "國防 / 無人機": 10,

        "機器人 / 自動化": 10,

        "資安": 9,

        "AI軟體": 8,

        "太空 / 衛星": 8,

        "AI生技 / 醫療科技": 8,

        "新能源 / 儲能 / 鈾": 8,

        "台股AI供應鏈": 10
    }

    bonus = 0

    for t in theme_list:

        bonus += priority.get(t, 0)

    return min(bonus, 18)

# =========================
# Playbook
# =========================

def playbook_level(score, risk_mode):

    if risk_mode:

        if score >= 90:

            return (
                "⚡ B級觀察",
                "小倉試單 5% 以下",
                "市場風險模式中"
            )

        elif score >= 78:

            return (
                "👀 C級觀察",
                "只觀察，不追高",
                "市場風險偏高"
            )

        else:

            return None, None, None

    # 正常模式

    if score >= 88:

        return (
            "🔥 A級主攻",
            "可分批 10%～20%",
            "主線強勢突破"
        )

    elif score >= 75:

        return (
            "⚡ B級觀察",
            "小倉 5%～10%",
            "等回測確認"
        )

    elif score >= 65:

        return (
            "👀 C級早期轉強",
            "觀察，不急著追",
            "可能剛轉強"
        )

    return None, None, None

# =========================
# 掃描
# =========================

def scan_stock(ticker, risk_mode=False):

    bm_ticker = benchmark_of(ticker)

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
        or
        len(bm) < 80
    ):
        return None

    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    price = float(close.iloc[-1])

    # ===== 均線 =====

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    # ===== 成交量 =====

    vol20 = volume.rolling(20).mean()

    volume_ratio = float(
        volume.iloc[-1]
        /
        vol20.iloc[-1]
    )

    # ===== RSI =====

    rsi = RSIIndicator(close).rsi()

    rsi_value = float(rsi.iloc[-1])

    # ===== MACD =====

    macd_obj = MACD(close)

    macd = macd_obj.macd()

    macd_signal = macd_obj.macd_signal()

    # ===== ATR =====

    atr = AverageTrueRange(
        high,
        low,
        close,
        window=14
    ).average_true_range()

    atr_value = float(atr.iloc[-1])

    atr_pct = atr_value / price

    # ===== Relative Strength =====

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

    # ===== 趨勢 =====

    above_ma20 = price > ma20.iloc[-1]

    above_ma50 = price > ma50.iloc[-1]

    ma20_up = (
        ma20.iloc[-1]
        >
        ma20.iloc[-5]
    )

    # ===== Breakout =====

    breakout_20d = (
        price
        >=
        close.rolling(20).max().iloc[-1] * 0.99
    )

    breakout_50d = (
        price
        >=
        close.rolling(50).max().iloc[-1] * 0.99
    )

    # ===== Compression =====

    compression = atr_pct < 0.055

    tight_range = (
        (
            high.iloc[-5:].max()
            -
            low.iloc[-5:].min()
        )
        /
        price
        <
        0.08
    )

    # ===== 假突破過濾 =====

    candle_range = (
        high.iloc[-1]
        -
        low.iloc[-1]
    )

    if candle_range == 0:

        upper_shadow_ratio = 0

    else:

        upper_shadow_ratio = (
            high.iloc[-1]
            -
            close.iloc[-1]
        ) / candle_range

    no_fake_breakout = (
        upper_shadow_ratio < 0.45
        and
        price < ma20.iloc[-1] * 1.12
    )

    # ===== Theme =====

    ticker_themes = themes_of(ticker)

    # =========================
    # Score
    # =========================

    score = 0

    if above_ma20:
        score += 8

    if above_ma50:
        score += 8

    if ma20_up:
        score += 8

    if volume_ratio >= 1.5:
        score += 15

    if 55 <= rsi_value <= 75:
        score += 8

    if macd.iloc[-1] > macd_signal.iloc[-1]:
        score += 8

    if breakout_20d:
        score += 12

    if breakout_50d:
        score += 12

    if rs_ok:
        score += 15

    if compression:
        score += 6

    if tight_range:
        score += 6

    score += theme_bonus(ticker_themes)

    if not no_fake_breakout:
        score -= 15

    if risk_mode:
        score -= 12

    # =========================
    # Strategy Tags
    # =========================

    strategies = []

    if breakout_20d or breakout_50d:
        strategies.append("Breakout")

    if compression and tight_range:
        strategies.append("Volatility Compression")

    if (
        price > ma20.iloc[-1]
        and
        price < close.rolling(20).max().iloc[-1] * 0.96
    ):
        strategies.append("Pullback Setup")

    if (
        rsi_value < 40
        and
        price > ma5.iloc[-1]
    ):
        strategies.append("Mean Reversion")

    # =========================
    # Playbook
    # =========================

    level, position_plan, note = playbook_level(
        score,
        risk_mode
    )

    if level is None:

        return None

    # =========================
    # Trading Plan
    # =========================

    entry = round(price, 2)

    stop = round(
        entry - atr_value * 2,
        2
    )

    tp1 = round(entry * 1.08, 2)

    tp2 = round(entry * 1.15, 2)

    tp3 = round(entry * 1.25, 2)

    # =========================
    # Message
    # =========================

    msg = f"""
{level}

股票：{ticker}

Theme：
{", ".join(ticker_themes)}

策略：
{", ".join(strategies) if strategies else "Trend / RS"}

價格：{entry}

總分：{score}/100

交易 Playbook：

建議動作：
{position_plan}

備註：
{note}

核心條件：

RS強於 {bm_ticker}：
{"是" if rs_ok else "否"}

放量倍數：
{round(volume_ratio, 2)}x

RSI：
{round(rsi_value, 2)}

ATR%：
{round(atr_pct * 100, 2)}%

20D突破：
{"是" if breakout_20d else "否"}

50D突破：
{"是" if breakout_50d else "否"}

假突破過濾：
{"通過" if no_fake_breakout else "未通過"}

交易計畫：

觀察區：
{entry}

ATR停損：
{stop}

TP1：
{tp1}

TP2：
{tp2}

TP3：
{tp3}
"""

    return {
        "ticker": ticker,
        "score": score,
        "themes": ticker_themes,
        "level": level,
        "message": msg
    }

# =========================
# 啟動
# =========================

send_telegram(
    "🚀 v10 Adaptive Theme Engine 已啟動"
)

# =========================
# 主迴圈
# =========================

while True:

    try:

        today = now_tw().strftime("%Y-%m-%d")

        watchlist = build_watchlist()

        active = [
            t
            for t in watchlist
            if market_open_for(t)
        ]

        if len(active) == 0:

            print("目前非開盤時間")

            time.sleep(SCAN_INTERVAL)

            continue

        risk_mode = market_risk_mode()

        results = []

        # =========================
        # 掃描
        # =========================

        for ticker in active:

            key = f"{today}-{ticker}"

            if key in sent_today:
                continue

            try:

                result = scan_stock(
                    ticker,
                    risk_mode
                )

                if result:

                    sent_today.add(key)

                    results.append(result)

            except Exception as e:

                print(ticker, e)

        # =========================
        # 排序
        # =========================

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

            level_count = {}

            for r in results:

                for th in r["themes"]:

                    theme_count[th] = (
                        theme_count.get(th, 0)
                        + 1
                    )

                level_count[r["level"]] = (
                    level_count.get(r["level"], 0)
                    + 1
                )

            summary = "📊 Adaptive Theme 主線偵測\n\n"

            # ===== Theme Ranking =====

            sorted_theme = sorted(
                theme_count.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for theme, count in sorted_theme:

                summary += f"{theme}: {count} 檔\n"

            summary += "\n📌 訊號等級\n"

            sorted_level = sorted(
                level_count.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for level, count in sorted_level:

                summary += f"{level}: {count} 檔\n"

            if risk_mode:

                summary += (
                    "\n⚠️ 市場風險模式啟動"
                    "\n系統已自動降權"
                )

            send_telegram(summary)

            send_telegram(
                f"🔥 本輪找到 {len(results)} 檔 Adaptive 訊號"
            )

            # ===== 前10檔 =====

            for r in results[:10]:

                send_telegram(r["message"])

        else:

            print("本輪沒有 Adaptive 訊號")

        # =========================
        # 清理
        # =========================

        if len(sent_today) > 500:

            sent_today.clear()

        # =========================
        # 等待
        # =========================

        time.sleep(SCAN_INTERVAL)

    except Exception as e:

        print("主程式錯誤：", e)

        time.sleep(60)