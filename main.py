import time
import requests
import yfinance as yf
import pandas as pd
from position_manager import manage_positions
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from leaderboard_engine import build_leaderboard, build_sector_rotation
from position_manager import manage_positions
from portfolio_engine import portfolio_risk_report
from analysis_engine import analyze_stock, format_telegram_message


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
# 持倉設定
# =========================
# 有持股可以填這裡，沒有就先空著
# 例如：{"AAOI": 500, "AXTI": 1000}

CURRENT_POSITIONS = {}


# =========================
# Theme Keywords
# =========================

THEME_KEYWORDS = {
    "AI基建": [
        "data", "cloud", "gpu", "server",
        "compute", "ai", "infrastructure"
    ],
    "光通訊": [
        "optical", "photonics", "laser",
        "fiber", "transceiver"
    ],
    "記憶體": [
        "memory", "dram", "storage",
        "flash", "ssd", "hbm"
    ],
    "電力": [
        "power", "energy", "grid",
        "nuclear", "utility", "electrical"
    ],
    "國防": [
        "defense", "drone", "military",
        "aerospace", "autonomous", "radar"
    ],
    "機器人": [
        "robot", "automation", "humanoid",
        "industrial"
    ],
    "資安": [
        "cyber", "security", "firewall",
        "endpoint", "network security"
    ],
    "太空": [
        "space", "satellite", "orbital",
        "rocket"
    ],
    "AI生技": [
        "biotech", "genomics", "drug",
        "medical", "healthcare"
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

    # Telegram 單則上限約 4096 字，保守切 3500
    chunks = [
        msg[i:i + 3500]
        for i in range(0, len(msg), 3500)
    ]

    for chunk in chunks:
        try:
            requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": chunk
                },
                timeout=10
            )
        except Exception as e:
            print("Telegram 發送失敗：", e)


# =========================
# 台股判定
# =========================

def is_tw(ticker):
    return ticker.endswith(".TW") or ticker.endswith(".TWO")


# =========================
# 市場時間
# =========================

def market_open_for(ticker):
    n = now_tw()
    minutes = n.hour * 60 + n.minute

    # 台股
    if is_tw(ticker):
        if n.weekday() >= 5:
            return False

        return 9 * 60 <= minutes <= 13 * 60 + 30

    # 美股，用台灣時間判斷
    # 夏令時間大約 21:30～04:00
    # 週一晚上～週六凌晨
    if minutes >= 21 * 60 + 30:
        return n.weekday() <= 4

    if minutes <= 4 * 60:
        return 1 <= n.weekday() <= 5

    return False


# =========================
# Benchmark
# =========================

def benchmark_of(ticker):
    if is_tw(ticker):
        return "0050.TW"

    return "QQQ"


# =========================
# yfinance 資料整理
# =========================

def normalize_yf_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    needed = ["Open", "High", "Low", "Close", "Volume"]

    for col in needed:
        if col not in df.columns:
            return pd.DataFrame()

    df = df[needed].dropna()

    return df


def download_price(ticker, period="1y"):
    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    return normalize_yf_df(df)


# =========================
# 市場風險模式
# =========================

def market_risk_mode():
    try:
        qqq = download_price("QQQ", "6mo")
        soxx = download_price("SOXX", "6mo")
        vix = download_price("^VIX", "3mo")

        if qqq.empty or soxx.empty or vix.empty:
            return False

        q = qqq["Close"]
        s = soxx["Close"]
        v = float(vix["Close"].iloc[-1])

        q_risk = q.iloc[-1] < q.rolling(20).mean().iloc[-1]
        s_risk = s.iloc[-1] < s.rolling(20).mean().iloc[-1]

        return q_risk or s_risk or v > 25

    except Exception as e:
        print("market_risk_mode 錯誤：", e)
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

        if "Test Issue" in df.columns:
            df = df[df["Test Issue"] == "N"]

        tickers = df["Symbol"].dropna().astype(str).tolist()

        tickers = [
            t for t in tickers
            if (
                "$" not in t
                and "." not in t
                and len(t) <= 5
                and t != "File Creation Time"
            )
        ]

        return tickers

    except Exception as e:
        print("get_us_market 錯誤：", e)
        return []


# =========================
# Theme 判定
# =========================

def detect_themes(ticker, info_text):
    hits = []
    text = str(info_text).lower()

    for theme, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                hits.append(theme)
                break

    if len(hits) == 0:
        hits.append("一般")

    return hits


def primary_theme(themes):
    if not themes:
        return "一般"

    return themes[0]


# =========================
# 股票掃描
# =========================

def scan_stock(ticker, risk_mode=False):
    try:
        bm_ticker = benchmark_of(ticker)

        stock = yf.Ticker(ticker)

        try:
            info = stock.info
            info_text = str(info.get("longBusinessSummary", ""))
        except Exception:
            info_text = ""

        themes = detect_themes(ticker, info_text)
        theme = primary_theme(themes)

        df = download_price(ticker, "1y")
        market_df = download_price(bm_ticker, "1y")

        if df.empty or market_df.empty:
            return None

        if len(df) < 220 or len(market_df) < 220:
            return None

        price = float(df["Close"].iloc[-1])

        # 過濾垃圾股
        if price < 5:
            return None

        avg_volume = df["Volume"].rolling(20).mean().iloc[-1]

        if avg_volume < 500000:
            return None

        current_position = CURRENT_POSITIONS.get(ticker, 0)

        result = analyze_stock(
            symbol=ticker,
            df=df,
            market_df=market_df,
            theme=theme,
            current_position=current_position
        )

        # 如果外部市場風險模式啟動，再額外扣分
        if risk_mode:
            result["score"] -= 2
            result["conditions"].append("外部市場風險模式啟動")

            if result["score"] < 10:
                return None

        # 發送門檻
        if result["score"] >= 12 and result["leader_score"] >= 50:
            msg = format_telegram_message(result)

            return {
                "ticker": ticker,
                "score": result["score"],
                "themes": themes,
                "message": msg
            }

        return None

    except Exception as e:
        print(f"{ticker} 掃描錯誤：", e)
        return None


# =========================
# 啟動
# =========================

send_telegram("🚀 v13 Institutional Alpha Engine 已啟動")


# =========================
# 主程式
# =========================

market_universe = get_us_market()

if not market_universe:
    send_telegram("⚠️ 股票池抓取失敗，請檢查 Nasdaq Trader 來源")

while True:
    try:
        today = now_tw().strftime("%Y-%m-%d")

        risk_mode = market_risk_mode()

        start = scan_pointer
        end = start + MAX_SCAN_PER_ROUND

        batch = market_universe[start:end]

        scan_pointer = end

        if scan_pointer >= len(market_universe):
            scan_pointer = 0

        # =========================
        # 持倉管理
        # =========================

        try:
            risk_report = portfolio_risk_report()

            if risk_report:
                send_telegram(risk_report)

        except Exception as e:
            print("portfolio_risk_report 錯誤：", e)

        try:
            position_msgs = manage_positions()

            for msg in position_msgs:
                send_telegram(msg)

        except Exception as e:
            print("manage_positions 錯誤：", e)

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
                ticker=ticker,
                risk_mode=risk_mode
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
                    theme_count[th] = theme_count.get(th, 0) + 1

            summary = "📊 Market Discovery 主線\n\n"

            sorted_theme = sorted(
                theme_count.items(),
                key=lambda x: x[1],
                reverse=True
            )

            for theme, count in sorted_theme:
                summary += f"{theme}: {count} 檔\n"

            if risk_mode:
                summary += "\n⚠️ 市場風險模式啟動"

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
from portfolio_engine import portfolio_risk_report
from analysis_engine import analyze_stock
from analysis_engine import format_telegram_message
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

# =========================
# 建議掛單價格
# =========================

def calculate_entry_plan(
    price,
    breakout_level,
    ma20_value,
    stop,
    current_position=0
):

    aggressive_low = round(price * 0.995, 2)
    aggressive_high = round(price * 1.002, 2)

    pullback_low = round(min(breakout_level, ma20_value), 2)
    pullback_high = round(max(breakout_level, ma20_value), 2)

    conservative_low = round(stop * 1.02, 2)
    conservative_high = round(stop * 1.05, 2)

    if current_position == 0:

        position_text = (
            "首次建倉：目標倉位 20%～30%\n"
            "突破確認後：再加 20%～30%"
        )

    else:

        add_20 = int(current_position * 0.2)
        add_30 = int(current_position * 0.3)

        position_text = (
            f"目前持股：{current_position} 股\n"
            f"建議加倉：{add_20}～{add_30} 股"
        )

    return {
        "aggressive_zone": f"{aggressive_low}～{aggressive_high}",
        "pullback_zone": f"{pullback_low}～{pullback_high}",
        "conservative_zone": f"{conservative_low}～{conservative_high}",
        "position_text": position_text
    }
# =========================
# K線 / 型態辨識模組
# =========================

def detect_chart_patterns(close, high, low, volume):
    patterns = []
    pattern_score = 0

    c = close
    h = high
    l = low
    v = volume

    if len(c) < 80:
        return patterns, pattern_score

    price = float(c.iloc[-1])

    # 1. Cup & Handle
    high_60 = c.iloc[-60:].max()
    low_60 = c.iloc[-60:].min()
    left_high = c.iloc[-60:-40].max()
    right_high = c.iloc[-20:].max()
    handle_low = c.iloc[-10:].min()

    cup_depth = (high_60 - low_60) / high_60
    handle_depth = (right_high - handle_low) / right_high

    cup_handle = (
        0.12 <= cup_depth <= 0.38
        and right_high >= left_high * 0.9
        and handle_depth <= 0.15
        and price >= right_high * 0.97
    )

    if cup_handle:
        patterns.append("Cup & Handle")
        pattern_score += 12

    # 2. VCP
    atr_short = (h.iloc[-10:].max() - l.iloc[-10:].min()) / price
    atr_mid = (h.iloc[-30:-10].max() - l.iloc[-30:-10].min()) / price
    atr_long = (h.iloc[-60:-30].max() - l.iloc[-60:-30].min()) / price

    vol_short = v.iloc[-10:].mean()
    vol_mid = v.iloc[-30:-10].mean()

    vcp = (
        atr_short < atr_mid
        and atr_mid < atr_long
        and vol_short < vol_mid
        and price >= c.iloc[-20:].max() * 0.97
    )

    if vcp:
        patterns.append("VCP")
        pattern_score += 12

    # 3. Bull Flag
    impulse = (c.iloc[-15] / c.iloc[-30]) - 1
    flag_pullback = (c.iloc[-15:].max() - c.iloc[-15:].min()) / c.iloc[-15:].max()
    recent_break = price >= c.iloc[-15:].max() * 0.98

    bull_flag = (
        impulse >= 0.18
        and flag_pullback <= 0.12
        and recent_break
        and v.iloc[-1] >= v.iloc[-20:].mean()
    )

    if bull_flag:
        patterns.append("Bull Flag")
        pattern_score += 10

    # 4. Flat Base
    base_range = (c.iloc[-40:].max() - c.iloc[-40:].min()) / c.iloc[-40:].max()
    flat_base = (
        base_range <= 0.18
        and price >= c.iloc[-40:].max() * 0.97
        and v.iloc[-1] >= v.iloc[-20:].mean() * 1.2
    )

    if flat_base:
        patterns.append("Flat Base")
        pattern_score += 10

    # 5. Inverse Head & Shoulders
    left_shoulder = c.iloc[-60:-45].min()
    head = c.iloc[-45:-25].min()
    right_shoulder = c.iloc[-25:-10].min()
    neckline = c.iloc[-25:].max()

    ihs = (
        head < left_shoulder
        and head < right_shoulder
        and right_shoulder >= head * 1.05
        and price >= neckline * 0.98
    )

    if ihs:
        patterns.append("Inverse H&S")
        pattern_score += 10

    if not patterns:
        patterns.append("無明顯型態")

    return patterns, pattern_score
# =========================
# 進階交易決策模組
# =========================

def trade_decision_engine(
    price,
    ma20_value,
    breakout_level,
    stop,
    tp1,
    score,
    rsi_value,
    volume_ratio,
    atr_pct,
    risk_mode,
    themes
):

    # RR Ratio
    risk = price - stop
    reward = tp1 - price

    if risk <= 0:
        rr_ratio = 0
    else:
        rr_ratio = round(reward / risk, 2)

    # 市場 Regime
    if risk_mode:
        market_regime = "Risk-Off 防守模式"
    elif score >= 88 and volume_ratio >= 1.5:
        market_regime = "Risk-On 強勢模式"
    else:
        market_regime = "Neutral 觀望模式"

    # 題材熱度
    if len(themes) >= 3:
        theme_heat = "🔥 高"
    elif len(themes) == 2:
        theme_heat = "⚡ 中高"
    elif len(themes) == 1 and themes[0] != "一般市場股":
        theme_heat = "🟡 中"
    else:
        theme_heat = "⚪ 低"

    # 勝率評級
    win_score = 0

    if score >= 88:
        win_score += 3
    elif score >= 75:
        win_score += 2
    elif score >= 65:
        win_score += 1

    if 55 <= rsi_value <= 70:
        win_score += 2
    elif 70 < rsi_value <= 78:
        win_score += 1

    if volume_ratio >= 2:
        win_score += 2
    elif volume_ratio >= 1.5:
        win_score += 1

    if rr_ratio >= 2:
        win_score += 2
    elif rr_ratio >= 1.5:
        win_score += 1

    if risk_mode:
        win_score -= 2

    if win_score >= 7:
        win_rate_grade = "A｜高勝率"
    elif win_score >= 5:
        win_rate_grade = "B｜中高勝率"
    elif win_score >= 3:
        win_rate_grade = "C｜普通"
    else:
        win_rate_grade = "D｜不建議追"

    # 自動判斷操作方式
    distance_from_ma20 = (price / ma20_value) - 1
    distance_from_breakout = (price / breakout_level) - 1

    if risk_mode:
        action = "禁止追價"
        reason = "市場風險模式啟動，優先防守"
        order_valid = "僅限當日，且不追高"

    elif rsi_value > 78:
        action = "禁止追價"
        reason = "RSI 過熱，容易短線回落"
        order_valid = "等待 1～3 日回測"

    elif rr_ratio < 1.2:
        action = "禁止追價"
        reason = "RR Ratio 不佳，風報比不足"
        order_valid = "等待更低掛單價"

    elif distance_from_ma20 > 0.08:
        action = "適合等回測"
        reason = "距離 20MA 偏遠，追價風險較高"
        order_valid = "1～3 日內有效"

    elif distance_from_breakout <= 0.03 and volume_ratio >= 1.5 and score >= 75:
        action = "適合追價"
        reason = "突破距離仍近，且量能確認"
        order_valid = "當日有效，不隔夜追價"

    else:
        action = "適合等回測"
        reason = "訊號成立，但尚未到最佳追價條件"
        order_valid = "1～3 日內有效"

    # 建議倉位 %
    if action == "禁止追價":
        position_pct = "0%"
    elif risk_mode:
        position_pct = "5%～10%"
    elif score >= 88 and rr_ratio >= 1.5:
        position_pct = "20%～30%"
    elif score >= 75:
        position_pct = "10%～20%"
    else:
        position_pct = "5%～10%"

    return {
        "action": action,
        "reason": reason,
        "order_valid": order_valid,
        "win_rate_grade": win_rate_grade,
        "rr_ratio": rr_ratio,
        "position_pct": position_pct,
        "market_regime": market_regime,
        "theme_heat": theme_heat
    }
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
        patterns, pattern_score = detect_chart_patterns(
            close,
            high,
            low,
            volume
        )
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
        score += pattern_score
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

        breakout_level = round(
            close.rolling(20).max().iloc[-2],
            2
        )

        entry_plan = calculate_entry_plan(
            price=entry,
            breakout_level=breakout_level,
            ma20_value=round(ma20.iloc[-1], 2),
            stop=stop,
            current_position=0
        )
        decision = trade_decision_engine(
            price=entry,
            ma20_value=round(ma20.iloc[-1], 2),
            breakout_level=breakout_level,
            stop=stop,
            tp1=tp1,
            score=score,
            rsi_value=rsi_value,
            volume_ratio=volume_ratio,
            atr_pct=atr_pct,
            risk_mode=risk_mode,
            themes=themes
)
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

━━━━━━━━━━
━━━━━━━━━━

🧠 自動交易判斷

操作建議：
{decision["action"]}

原因：
{decision["reason"]}

掛單有效時間：
{decision["order_valid"]}

勝率評級：
{decision["win_rate_grade"]}

RR Ratio：
{decision["rr_ratio"]}

建議倉位：
{decision["position_pct"]}

市場 Regime：
{decision["market_regime"]}

題材熱度：
{decision["theme_heat"]}
🎯 建議掛單價格

1️⃣ 積極追價區：
{entry_plan["aggressive_zone"]}

2️⃣ 回測掛單區：
{entry_plan["pullback_zone"]}

3️⃣ 保守低接區：
{entry_plan["conservative_zone"]}

━━━━━━━━━━

📦 倉位建議

{entry_plan["position_text"]}

━━━━━━━━━━

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
        risk_report = portfolio_risk_report()

        if risk_report:
            send_telegram(risk_report)
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