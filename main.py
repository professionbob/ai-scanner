import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

from position_manager import manage_positions
from portfolio_engine import portfolio_risk_report
from analysis_engine import analyze_stock, format_telegram_message
from leaderboard_engine import build_leaderboard, build_sector_rotation


# =========================
# Telegram
# =========================

BOT_TOKEN = "8525756263:AAHE4WHHmYn6QKT3q-PWMux_XuCadU0it1A"
CHAT_ID = "8851496243"


# =========================
# Config
# =========================

SCAN_INTERVAL = 300
MAX_SCAN_PER_ROUND = 100

SIGNAL_SCORE_MIN = 8
SIGNAL_LEADER_MIN = 30
RANKING_SCORE_MIN = 0

TEST_MODE = True

ENABLE_OPTIONS_FLOW = True
ENABLE_DARK_POOL = True
ENABLE_INSTITUTIONAL_FLOW = True

# 沒有暗池 API 就留空，系統會自動使用量價代理模型
DARK_POOL_API_KEY = ""

sent_today = set()
signal_state = {}
sent_msg_cache = set()
trade_recommendations = {}

scan_pointer = 0
last_close_report_date = None
last_premarket_report_date = None
last_ai_infra_report_date = None

TW_CLOSE_REPORT_TIME = 13 * 60 + 45
US_CLOSE_REPORT_TIME = 5 * 60 + 10
TW_PREMARKET_REPORT_TIME = 8 * 60 + 45
US_PREMARKET_REPORT_TIME = 21 * 60 + 15

# 報告節流，避免每一輪重複送
PURE_RANKING_INTERVAL_MINUTES = 30
ROTATION_INTERVAL_MINUTES = 60
SUMMARY_INTERVAL_MINUTES = 30
PORTFOLIO_REPORT_INTERVAL_MINUTES = 30


# =========================
# Retail Edge / 少盯盤模式
# =========================

RETAIL_EDGE_MODE = True

MAX_CHASE_ABOVE_MA20 = 1.12
EXTREME_CHASE_ABOVE_MA20 = 1.18

MIN_SMART_MONEY_FOR_SIGNAL = 3
MIN_VOLUME_RATIO_FOR_SIGNAL = 1.1

BASE_POSITION_PCT = {
    "S": 10,
    "A": 7,
    "B": 4,
    "C": 2,
    "WAIT": 0,
}


# =========================
# Signal Tier / 正式推薦分級
# =========================

ENABLE_SIGNAL_TIER = True

S_SIGNAL_SCORE_MIN = 12
S_LEADER_SCORE_MIN = 45
S_SMART_MONEY_MIN = 6

A_SIGNAL_SCORE_MIN = 10
A_LEADER_SCORE_MIN = 35
A_SMART_MONEY_MIN = 3

WATCH_SCORE_MIN = 8
WATCH_LEADER_MIN = 30


# =========================
# 持倉設定
# =========================

CURRENT_POSITIONS = {
    # "AAOI": 500,
    # "AXTI": 1000,
}


# =========================
# Theme Keywords
# =========================

THEME_KEYWORDS = {
    "AI基建": ["data", "cloud", "gpu", "server", "compute", "ai", "infrastructure"],
    "光通訊": ["optical", "photonics", "laser", "fiber", "transceiver"],
    "記憶體": ["memory", "dram", "storage", "flash", "ssd", "hbm"],
    "電力": ["power", "energy", "grid", "nuclear", "utility", "electrical"],
    "國防": ["defense", "drone", "military", "aerospace", "autonomous", "radar"],
    "機器人": ["robot", "automation", "humanoid", "industrial"],
    "資安": ["cyber", "security", "firewall", "endpoint", "network security"],
    "太空": ["space", "satellite", "orbital", "rocket"],
    "AI生技": ["biotech", "genomics", "drug", "medical", "healthcare"],
}


# =========================
# AI 基建主題池
# =========================

ADVANCED_PACKAGING = [
    "3583.TW",  # 辛耘
    "3131.TW",  # 弘塑
    "5443.TW",  # 均豪
    "2467.TW",  # 志聖
    "6187.TW",  # 萬潤
    "6640.TW",  # 均華
]

CLEANROOM = [
    "2404.TW",  # 漢唐
    "6196.TW",  # 帆宣
    "5536.TW",  # 聖暉*
    "6691.TW",  # 洋基工程
    "6139.TW",  # 亞翔
    "6667.TW",  # 信紘科
]

ADVANCED_PCB_SUBSTRATE = [
    "3037.TW",  # 欣興
    "3189.TW",  # 景碩
    "8046.TW",  # 南電
    "2368.TW",  # 金像電
]

TW_OPTICAL = [
    "3450.TW",  # 聯鈞
    "3163.TW",  # 波若威
    "4979.TW",  # 華星光
    "3234.TW",  # 光環
    "3363.TW",  # 上詮
]

POWER_GRID = [
    "1519.TW",  # 華城
    "1503.TW",  # 士電
    "1513.TW",  # 中興電
]

COOLING = [
    "3017.TW",  # 奇鋐
    "3324.TW",  # 雙鴻
]

AI_INFRA_THEMES = list(dict.fromkeys(
    ADVANCED_PACKAGING
    + CLEANROOM
    + ADVANCED_PCB_SUBSTRATE
    + TW_OPTICAL
    + POWER_GRID
    + COOLING
))

THEME_GROUPS = {
    "先進封裝": ADVANCED_PACKAGING,
    "無塵室/廠務": CLEANROOM,
    "ABF/載板": ADVANCED_PCB_SUBSTRATE,
    "光通訊": TW_OPTICAL,
    "電力": POWER_GRID,
    "散熱": COOLING,
}

THEME_BONUS = {
    "先進封裝": 3,
    "無塵室/廠務": 2,
    "ABF/載板": 2,
    "光通訊": 2,
    "電力": 1,
    "散熱": 1,
}


# =========================
# 時間 / 去重
# =========================

def now_tw():
    return datetime.utcnow() + timedelta(hours=8)


def mark_once_interval(key, minutes):
    n = now_tw()
    today = n.strftime("%Y-%m-%d")
    bucket = (n.hour * 60 + n.minute) // minutes
    full_key = f"{today}-{key}-{bucket}"

    if full_key in sent_today:
        return False

    sent_today.add(full_key)
    return True


def mark_once_daily(key):
    today = now_tw().strftime("%Y-%m-%d")
    full_key = f"{today}-{key}"

    if full_key in sent_today:
        return False

    sent_today.add(full_key)
    return True


# =========================
# Telegram
# =========================

def send_telegram(msg):
    if not msg:
        return

    if not BOT_TOKEN or BOT_TOKEN == "請填入你的Telegram Bot Token":
        print("Telegram Bot Token 尚未設定，訊息未發送：")
        print(str(msg)[:800])
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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


def send_telegram_once(msg):
    global sent_msg_cache

    if not msg:
        return

    key = msg.strip()

    if key in sent_msg_cache:
        return

    sent_msg_cache.add(key)
    send_telegram(msg)


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

    if is_tw(ticker):
        if n.weekday() >= 5:
            return False

        return 9 * 60 <= minutes <= 13 * 60 + 30

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

    return df[needed].dropna()


def download_price(ticker, period="1y"):
    try:
        df = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False
        )
        return normalize_yf_df(df)
    except Exception as e:
        print(f"{ticker} 下載資料錯誤：", e)
        return pd.DataFrame()


# =========================
# 期權 Flow 分析
# =========================

def analyze_options_flow(ticker, price):
    default_result = {
        "options_score": 0,
        "options_note": "期權資料不足",
        "hot_call_strikes": [],
        "hot_put_strikes": [],
        "call_put_volume_ratio": None,
        "call_put_oi_ratio": None,
        "max_pain": None,
    }

    if is_tw(ticker):
        return default_result

    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options

        if not expirations:
            return default_result

        nearest_exp = expirations[0]
        chain = stock.option_chain(nearest_exp)

        calls = chain.calls.copy()
        puts = chain.puts.copy()

        if calls.empty or puts.empty:
            return default_result

        calls = calls.dropna(subset=["strike"])
        puts = puts.dropna(subset=["strike"])

        calls["volume"] = calls["volume"].fillna(0)
        puts["volume"] = puts["volume"].fillna(0)
        calls["openInterest"] = calls["openInterest"].fillna(0)
        puts["openInterest"] = puts["openInterest"].fillna(0)

        call_volume = calls["volume"].sum()
        put_volume = puts["volume"].sum()
        call_oi = calls["openInterest"].sum()
        put_oi = puts["openInterest"].sum()

        call_put_volume_ratio = round(call_volume / put_volume, 2) if put_volume > 0 else None
        call_put_oi_ratio = round(call_oi / put_oi, 2) if put_oi > 0 else None

        near_calls = calls[
            (calls["strike"] >= price * 0.9) &
            (calls["strike"] <= price * 1.25)
        ]

        near_puts = puts[
            (puts["strike"] >= price * 0.75) &
            (puts["strike"] <= price * 1.1)
        ]

        hot_call_strikes = (
            near_calls.sort_values(["volume", "openInterest"], ascending=False)
            .head(3)["strike"]
            .tolist()
        )

        hot_put_strikes = (
            near_puts.sort_values(["volume", "openInterest"], ascending=False)
            .head(3)["strike"]
            .tolist()
        )

        all_strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        pain_rows = []

        for strike in all_strikes:
            call_loss = ((calls["strike"] - strike).clip(lower=0) * calls["openInterest"]).sum()
            put_loss = ((strike - puts["strike"]).clip(lower=0) * puts["openInterest"]).sum()
            pain_rows.append((strike, call_loss + put_loss))

        max_pain = min(pain_rows, key=lambda x: x[1])[0] if pain_rows else None

        score = 0
        notes = []

        if call_put_volume_ratio and call_put_volume_ratio >= 1.5:
            score += 1
            notes.append(f"Call 量大於 Put，C/P量比 {call_put_volume_ratio}")

        if call_put_volume_ratio and call_put_volume_ratio >= 2.5:
            score += 1
            notes.append("Call 追價情緒偏強")

        if call_put_oi_ratio and call_put_oi_ratio >= 1.3:
            score += 1
            notes.append(f"Call OI 大於 Put，C/P OI比 {call_put_oi_ratio}")

        if max_pain and price > max_pain:
            score += 1
            notes.append(f"股價高於 Max Pain 約 {round(max_pain, 2)}，短線偏多")

        if hot_call_strikes:
            notes.append(f"熱門 Call 履約價：{', '.join([str(round(x, 2)) for x in hot_call_strikes])}")

        if hot_put_strikes:
            notes.append(f"熱門 Put 履約價：{', '.join([str(round(x, 2)) for x in hot_put_strikes])}")

        if not notes:
            notes.append("期權結構中性")

        return {
            "options_score": score,
            "options_note": "；".join(notes),
            "hot_call_strikes": hot_call_strikes,
            "hot_put_strikes": hot_put_strikes,
            "call_put_volume_ratio": call_put_volume_ratio,
            "call_put_oi_ratio": call_put_oi_ratio,
            "max_pain": max_pain,
        }

    except Exception as e:
        print(f"{ticker} 期權分析錯誤：", e)
        return default_result


# =========================
# 暗池 / 大宗交易代理判斷
# =========================

def analyze_dark_pool_proxy(ticker, df):
    default_result = {
        "dark_pool_score": 0,
        "dark_pool_note": "暗池資料不足，使用量價代理模型",
        "dark_pool_bias": "neutral",
    }

    try:
        if df.empty or len(df) < 60:
            return default_result

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        open_price = df["Open"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        vol20 = volume.rolling(20).mean().iloc[-1]
        vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

        day_return = (price / prev_price - 1) * 100
        candle_range = high.iloc[-1] - low.iloc[-1]

        upper_shadow = high.iloc[-1] - max(close.iloc[-1], open_price.iloc[-1])
        lower_shadow = min(close.iloc[-1], open_price.iloc[-1]) - low.iloc[-1]

        upper_shadow_ratio = upper_shadow / candle_range if candle_range > 0 else 0
        lower_shadow_ratio = lower_shadow / candle_range if candle_range > 0 else 0

        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]

        score = 0
        notes = []
        bias = "neutral"

        if vol_ratio >= 1.5 and day_return >= 0:
            score += 1
            notes.append(f"放量不跌，量能 {round(vol_ratio, 2)}x，疑似大單承接")
            bias = "accumulation"

        if vol_ratio >= 2 and day_return > 2:
            score += 1
            notes.append("放量上漲，疑似主力推升")
            bias = "accumulation"

        if price > ma20 and price > ma50 and vol_ratio >= 1.2:
            score += 1
            notes.append("站上20MA/50MA且量能放大，籌碼偏多")

        if upper_shadow_ratio >= 0.45 and vol_ratio >= 1.8:
            score -= 2
            notes.append("高量長上影，疑似上方派發")
            bias = "distribution"

        if day_return < -3 and vol_ratio >= 1.8:
            score -= 2
            notes.append("放量下跌，疑似主力出貨")
            bias = "distribution"

        if lower_shadow_ratio >= 0.4 and vol_ratio >= 1.3:
            score += 1
            notes.append("下影線承接明顯，疑似買盤防守")
            bias = "accumulation"

        if not notes:
            notes.append("量價結構中性，未見明顯主力痕跡")

        return {
            "dark_pool_score": score,
            "dark_pool_note": "；".join(notes),
            "dark_pool_bias": bias,
        }

    except Exception as e:
        print(f"{ticker} 暗池代理分析錯誤：", e)
        return default_result


def analyze_dark_pool_api(ticker):
    if not DARK_POOL_API_KEY:
        return None

    try:
        return None

    except Exception as e:
        print(f"{ticker} 暗池 API 錯誤：", e)
        return None


def analyze_dark_pool(ticker, df):
    api_result = analyze_dark_pool_api(ticker)

    if api_result:
        return api_result

    return analyze_dark_pool_proxy(ticker, df)


# =========================
# 機構 / 主力進出判斷
# =========================

def analyze_institutional_flow(ticker, df, market_df):
    default_result = {
        "institutional_score": 0,
        "institutional_note": "機構主力資料不足",
        "institutional_bias": "neutral",
    }

    try:
        if df.empty or market_df.empty or len(df) < 80 or len(market_df) < 80:
            return default_result

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        market_close = market_df["Close"]

        price = float(close.iloc[-1])

        stock_20d_return = close.iloc[-1] / close.iloc[-20] - 1
        market_20d_return = market_close.iloc[-1] / market_close.iloc[-20] - 1

        rs_strength = stock_20d_return > market_20d_return

        obv = []
        current_obv = 0

        for i in range(1, len(df)):
            if close.iloc[i] > close.iloc[i - 1]:
                current_obv += volume.iloc[i]
            elif close.iloc[i] < close.iloc[i - 1]:
                current_obv -= volume.iloc[i]

            obv.append(current_obv)

        obv_series = pd.Series(obv)
        obv_up = obv_series.iloc[-1] > obv_series.rolling(20).mean().iloc[-1]

        money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
        money_flow_multiplier = money_flow_multiplier.replace(
            [float("inf"), -float("inf")],
            0
        ).fillna(0)

        money_flow_volume = money_flow_multiplier * volume
        ad_line = money_flow_volume.cumsum()
        ad_up = ad_line.iloc[-1] > ad_line.rolling(20).mean().iloc[-1]

        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]

        vol20 = volume.rolling(20).mean().iloc[-1]
        vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

        recent_high = close.rolling(60).max().iloc[-2]
        breakout = price > recent_high and vol_ratio >= 1.3

        pullback_volume_dry = (
            price > ma20 and
            volume.iloc[-1] < vol20 and
            close.iloc[-1] >= close.iloc[-2] * 0.98
        )

        score = 0
        notes = []
        bias = "neutral"

        if rs_strength:
            score += 1
            notes.append("20日相對強度優於大盤")

        if obv_up:
            score += 1
            notes.append("OBV走升，籌碼偏向流入")

        if ad_up:
            score += 1
            notes.append("A/D Line走升，疑似資金累積")

        if breakout:
            score += 2
            notes.append("放量突破60日高點，疑似機構推升")

        if pullback_volume_dry:
            score += 1
            notes.append("回測縮量不破，籌碼穩定")

        if price < ma20 and price < ma50:
            score -= 2
            notes.append("跌破20MA/50MA，主力結構偏弱")

        if vol_ratio >= 2 and close.iloc[-1] < close.iloc[-2]:
            score -= 2
            notes.append("放量收跌，疑似主力出貨")

        if score >= 3:
            bias = "inflow"
        elif score <= -2:
            bias = "outflow"

        if not notes:
            notes.append("未見明顯機構進出訊號")

        return {
            "institutional_score": score,
            "institutional_note": "；".join(notes),
            "institutional_bias": bias,
        }

    except Exception as e:
        print(f"{ticker} 機構主力分析錯誤：", e)
        return default_result


# =========================
# Smart Money 整合
# =========================

def build_smart_money_summary(options_data, dark_pool_data, institutional_data):
    total_score = (
        options_data.get("options_score", 0)
        + dark_pool_data.get("dark_pool_score", 0)
        + institutional_data.get("institutional_score", 0)
    )

    notes = []

    if options_data.get("options_note"):
        notes.append(f"期權：{options_data['options_note']}")

    if dark_pool_data.get("dark_pool_note"):
        notes.append(f"暗池/量價：{dark_pool_data['dark_pool_note']}")

    if institutional_data.get("institutional_note"):
        notes.append(f"機構：{institutional_data['institutional_note']}")

    if total_score >= 6:
        bias = "強烈偏多"
    elif total_score >= 3:
        bias = "偏多"
    elif total_score <= -3:
        bias = "偏空"
    else:
        bias = "中性"

    return {
        "smart_money_score": total_score,
        "smart_money_bias": bias,
        "smart_money_note": "\n".join(notes),
    }


def append_smart_money_to_message(msg, result):
    smart_score = result.get("smart_money_score")
    smart_bias = result.get("smart_money_bias")
    smart_note = result.get("smart_money_note")

    if smart_score is None:
        return msg

    extra = "\n\n🏦 Smart Money / 期權 / 暗池觀察\n"
    extra += f"Smart Money Score：{smart_score}\n"
    extra += f"主力傾向：{smart_bias}\n"

    if result.get("call_put_volume_ratio"):
        extra += f"Call/Put Volume Ratio：{result.get('call_put_volume_ratio')}\n"

    if result.get("call_put_oi_ratio"):
        extra += f"Call/Put OI Ratio：{result.get('call_put_oi_ratio')}\n"

    if result.get("max_pain"):
        extra += f"Max Pain：約 {round(result.get('max_pain'), 2)}\n"

    if smart_note:
        extra += f"\n{smart_note}"

    return msg + extra


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
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        sp500_df = tables[0]

        sp500 = (
            sp500_df["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .tolist()
        )

        ai_growth = [
            "CRWV", "NBIS", "APLD", "CORZ",
            "IREN", "CLS", "AAOI", "FN",
            "AXTI", "AEHR", "ONTO", "MKSI",
            "SERV", "SYM", "KTOS", "AVAV",
            "SOFI", "HOOD", "COIN"
        ]

        etf = [
            "QQQ",
            "SOXX",
            "SPY"
        ]

        all_tickers = (
            sp500
            + ai_growth
            + etf
        )

        return list(dict.fromkeys(all_tickers))

    except Exception as e:
        print("get_us_market 錯誤：", e)

        return [
            "NVDA", "MSFT", "AMZN", "META",
            "GOOGL", "AAPL", "AVGO", "AMD"
        ]


def get_tw_market():
    tw50 = [
        "2330.TW", "2317.TW", "2454.TW", "2308.TW",
        "2881.TW", "2882.TW", "1303.TW", "1301.TW",
        "2412.TW", "2886.TW", "2891.TW", "2884.TW",
        "2885.TW", "3711.TW", "1216.TW", "2002.TW",
        "2880.TW", "2892.TW", "3045.TW", "2207.TW",
        "2603.TW", "5880.TW", "6505.TW", "2883.TW",
        "2382.TW", "3034.TW", "2327.TW", "2303.TW",
        "3008.TW", "2887.TW", "2912.TW", "5871.TW",
        "1101.TW", "1590.TW", "4904.TW", "2379.TW",
        "5876.TW", "6415.TW", "4938.TW", "6669.TW",
        "3533.TW", "1326.TW", "2408.TW", "2609.TW",
        "2615.TW", "6446.TW", "3661.TW", "2357.TW",
        "2890.TW"
    ]

    ai_growth = [
        "3017.TW", "6669.TW", "3231.TW", "3450.TW",
        "4979.TW", "4908.TW", "3443.TW", "3653.TW",
        "2049.TW", "3324.TW", "2368.TW", "3037.TW",
        "1519.TW", "1503.TW", "1513.TW"
    ]

    etf = ["0050.TW", "006208.TW"]

    all_tickers = tw50 + ai_growth + AI_INFRA_THEMES + etf

    return list(dict.fromkeys(all_tickers))


# =========================
# Theme 判定
# =========================

def detect_themes(ticker, info_text):
    hits = []

    for theme, tickers in THEME_GROUPS.items():
        if ticker in tickers:
            hits.append(theme)

    text = str(info_text).lower()

    for theme, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                hits.append(theme)
                break

    hits = list(dict.fromkeys(hits))

    if len(hits) == 0:
        hits.append("一般")

    return hits


def primary_theme(themes):
    if not themes:
        return "一般"

    return themes[0]


# =========================
# 訊號升級判定
# =========================

def should_send_signal(result):
    ticker = result["ticker"]
    today = now_tw().strftime("%Y-%m-%d")
    key = f"{today}-{ticker}"

    score = result.get("score", 0)
    leader_score = result.get("leader_score", 0)
    price = result.get("price", 0)
    msg = result.get("message", "")

    if key not in signal_state:
        signal_state[key] = {
            "score": score,
            "leader_score": leader_score,
            "price": price,
            "last_msg": msg,
            "alert_count": 1
        }
        return True, "首次正式訊號"

    prev = signal_state[key]
    reasons = []

    if score >= prev["score"] + 2:
        reasons.append(f"分數升級 {prev['score']} → {score}")

    if leader_score >= prev["leader_score"] + 10:
        reasons.append(f"Leader Score 升級 {prev['leader_score']} → {leader_score}")

    if prev["price"] and price >= prev["price"] * 1.03:
        reasons.append(f"價格加速 +{round((price / prev['price'] - 1) * 100, 2)}%")

    if prev["alert_count"] >= 3:
        return False, ""

    if reasons:
        signal_state[key] = {
            "score": max(score, prev["score"]),
            "leader_score": max(leader_score, prev["leader_score"]),
            "price": price,
            "last_msg": msg,
            "alert_count": prev["alert_count"] + 1
        }

        return True, " / ".join(reasons)

    return False, ""


# =========================
# 記錄推薦價
# =========================

def record_recommendation(result):
    today = now_tw().strftime("%Y-%m-%d")
    ticker = result["ticker"]
    key = f"{today}-{ticker}"

    if key in trade_recommendations:
        return

    trade_recommendations[key] = {
        "date": today,
        "ticker": ticker,
        "entry_price": result.get("price", 0),
        "score": result.get("score", 0),
        "leader_score": result.get("leader_score", 0),
        "themes": result.get("themes", []),
        "setup_grade": result.get("setup_grade", ""),
        "market_regime": result.get("market_regime", ""),
        "smart_money_score": result.get("smart_money_score", 0),
        "smart_money_bias": result.get("smart_money_bias", "中性"),
    }


# =========================
# Retail Edge Engine
# =========================

def detect_earnings_risk(ticker):
    default = {
        "earnings_risk": False,
        "earnings_note": "財報日期無法確認",
        "days_to_earnings": None,
    }

    if is_tw(ticker):
        return default

    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar

        if cal is None or len(cal) == 0:
            return default

        earnings_date = None

        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if isinstance(raw, list) and raw:
                earnings_date = raw[0]
            else:
                earnings_date = raw

        elif isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"][0]
                earnings_date = raw

        if earnings_date is None:
            return default

        earnings_date = pd.to_datetime(earnings_date).to_pydatetime()
        now = datetime.utcnow()
        days = (earnings_date.date() - now.date()).days

        if 0 <= days <= 14:
            return {
                "earnings_risk": True,
                "earnings_note": f"財報可能在 {days} 天內，避免重倉追價",
                "days_to_earnings": days,
            }

        return {
            "earnings_risk": False,
            "earnings_note": f"距離財報約 {days} 天",
            "days_to_earnings": days,
        }

    except Exception as e:
        print(f"{ticker} 財報日期偵測錯誤：", e)
        return default


def classify_setup(result, df):
    close = df["Close"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    vol20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

    smart = result.get("smart_money_score", 0)
    score = result.get("score", 0)
    leader = result.get("leader_score", 0)

    extended = price > ma20 * MAX_CHASE_ABOVE_MA20
    extreme_extended = price > ma20 * EXTREME_CHASE_ABOVE_MA20

    if extreme_extended:
        return "WAIT", "嚴重乖離20MA，只等回測"

    if price < ma20 or price < ma50:
        return "C", "趨勢未完全站穩，僅觀察或小倉"

    if smart >= 6 and score >= 12 and leader >= 45 and vol_ratio >= 1.3 and not extended:
        return "S", "Institutional Trend：機構趨勢主升段"

    if smart >= 3 and score >= 10 and leader >= 35 and vol_ratio >= 1.1 and not extended:
        return "A", "Momentum Breakout：高品質突破"

    if score >= 8 and leader >= 30:
        return "B", "一般強勢股，但需等好價格"

    return "C", "訊號普通，僅列入觀察"


def build_entry_plan(result, df):
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    price = float(close.iloc[-1])

    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]

    recent_high = high.rolling(20).max().iloc[-2]
    recent_low = low.rolling(20).min().iloc[-1]

    stop = min(ma20, recent_low) * 0.97

    aggressive_entry = price
    pullback_entry_1 = ma10
    pullback_entry_2 = ma20
    breakout_entry = recent_high

    max_chase_price = ma20 * MAX_CHASE_ABOVE_MA20

    rr_target = price + (price - stop) * 2
    rr_ratio = (rr_target - price) / (price - stop) if price > stop else 0

    if price > max_chase_price:
        action = "禁止追價，等回測"
    elif price > recent_high:
        action = "突破中，可小倉追，主倉等回測"
    elif price >= ma10:
        action = "趨勢內，可等10MA附近"
    else:
        action = "等20MA或箱型支撐"

    return {
        "entry_action": action,
        "aggressive_entry": round(aggressive_entry, 2),
        "pullback_entry_1": round(pullback_entry_1, 2),
        "pullback_entry_2": round(pullback_entry_2, 2),
        "breakout_entry": round(breakout_entry, 2),
        "max_chase_price": round(max_chase_price, 2),
        "stop_loss": round(stop, 2),
        "rr_ratio": round(rr_ratio, 2),
    }


def recommend_position_size(setup_grade, result, earnings_data, risk_mode):
    pct = BASE_POSITION_PCT.get(setup_grade, 0)

    smart = result.get("smart_money_score", 0)

    if smart <= 0:
        pct -= 2

    if earnings_data.get("earnings_risk"):
        pct -= 3

    if risk_mode:
        pct -= 3

    if setup_grade == "WAIT":
        pct = 0

    pct = max(0, pct)

    if pct >= 8:
        label = "可作為主力倉位"
    elif pct >= 4:
        label = "中等倉位"
    elif pct > 0:
        label = "小倉觀察"
    else:
        label = "不建議新倉"

    return {
        "position_pct": pct,
        "position_label": label,
    }


def apply_retail_edge_filters(result, df, risk_mode):
    close = df["Close"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    vol20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

    price_extended = price > ma20 * MAX_CHASE_ABOVE_MA20
    very_extended = price > ma20 * EXTREME_CHASE_ABOVE_MA20

    if price_extended:
        result["score"] -= 2
        result["leader_score"] -= 5
        result["conditions"].append("短線漲幅偏高，避免追價")

    if very_extended:
        result["score"] -= 3
        result["leader_score"] -= 10
        result["conditions"].append("嚴重乖離20MA，只等回測")

    high_quality_signal = (
        result["score"] >= SIGNAL_SCORE_MIN
        and result["leader_score"] >= SIGNAL_LEADER_MIN
        and result.get("smart_money_score", 0) >= MIN_SMART_MONEY_FOR_SIGNAL
        and not very_extended
        and price > ma20
        and price > ma50
        and vol_ratio >= MIN_VOLUME_RATIO_FOR_SIGNAL
        and not risk_mode
    )

    if high_quality_signal:
        result["conditions"].append("高品質訊號：趨勢、量能、Smart Money 同步")

    return high_quality_signal


def append_retail_edge_to_message(msg, result):
    extra = "\n\n🎯 Retail Edge 少盯盤建議\n"

    extra += f"Setup 等級：{result.get('retail_setup_grade', 'N/A')}\n"
    extra += f"Setup 類型：{result.get('setup_type_note', 'N/A')}\n"
    extra += f"建議倉位：{result.get('position_pct', 0)}%｜{result.get('position_label', 'N/A')}\n"

    entry = result.get("entry_plan", {})

    if entry:
        extra += "\n掛單計畫：\n"
        extra += f"策略：{entry.get('entry_action')}\n"
        extra += f"可追價上限：{entry.get('max_chase_price')}\n"
        extra += f"積極價：{entry.get('aggressive_entry')}\n"
        extra += f"回測價1：{entry.get('pullback_entry_1')}\n"
        extra += f"回測價2：{entry.get('pullback_entry_2')}\n"
        extra += f"突破價：{entry.get('breakout_entry')}\n"
        extra += f"停損：{entry.get('stop_loss')}\n"
        extra += f"RR Ratio：約 {entry.get('rr_ratio')}\n"

    earnings_note = result.get("earnings_note")

    if earnings_note:
        extra += f"\n財報風險：{earnings_note}\n"

    return msg + extra


# =========================
# Signal Tier Engine
# =========================

def classify_signal_tier(result, df, risk_mode):
    close = df["Close"]
    volume = df["Volume"]

    price = float(close.iloc[-1])
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    vol20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

    score = result.get("score", 0)
    leader = result.get("leader_score", 0)
    smart = result.get("smart_money_score", 0)
    setup_grade = result.get("retail_setup_grade", "C")
    earnings_risk = result.get("earnings_risk", False)

    very_extended = price > ma20 * EXTREME_CHASE_ABOVE_MA20
    extended = price > ma20 * MAX_CHASE_ABOVE_MA20

    base_trend_ok = (
        price > ma20
        and price > ma50
        and vol_ratio >= MIN_VOLUME_RATIO_FOR_SIGNAL
        and not very_extended
    )

    if risk_mode:
        return {
            "signal_tier": "NO_TRADE",
            "signal_action": "市場風險模式，不發正式推薦",
            "send_signal": False,
        }

    if earnings_risk:
        return {
            "signal_tier": "WATCH",
            "signal_action": "財報前風險，只觀察不重倉",
            "send_signal": False,
        }

    if (
        score >= S_SIGNAL_SCORE_MIN
        and leader >= S_LEADER_SCORE_MIN
        and smart >= S_SMART_MONEY_MIN
        and setup_grade == "S"
        and base_trend_ok
        and not extended
    ):
        return {
            "signal_tier": "S",
            "signal_action": "S級正式推薦：機構主升段，可作主力倉位",
            "send_signal": True,
        }

    if (
        score >= A_SIGNAL_SCORE_MIN
        and leader >= A_LEADER_SCORE_MIN
        and smart >= A_SMART_MONEY_MIN
        and setup_grade in ["S", "A"]
        and base_trend_ok
    ):
        return {
            "signal_tier": "A",
            "signal_action": "A級正式推薦：可建倉，但避免追高",
            "send_signal": True,
        }

    if (
        score >= WATCH_SCORE_MIN
        and leader >= WATCH_LEADER_MIN
        and price > ma20
        and price > ma50
    ):
        return {
            "signal_tier": "WATCH",
            "signal_action": "Watchlist：接近高品質，但等待回測或量價確認",
            "send_signal": False,
        }

    return {
        "signal_tier": "NO_TRADE",
        "signal_action": "未達正式推薦標準",
        "send_signal": False,
    }


def append_signal_tier_to_message(msg, result):
    tier = result.get("signal_tier", "NO_TRADE")
    action = result.get("signal_action", "")

    extra = "\n\n🏷 正式推薦分級\n"
    extra += f"等級：{tier}\n"
    extra += f"判斷：{action}\n"

    return msg + extra


# =========================
# 股票掃描
# =========================

def scan_stock(ticker, risk_mode=False, force_return=False):
    try:
        bm_ticker = benchmark_of(ticker)

        try:
            stock = yf.Ticker(ticker)
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

        if price < 5:
            return None

        avg_volume = df["Volume"].rolling(20).mean().iloc[-1]

        if avg_volume < 500000:
            return None

        options_data = {
            "options_score": 0,
            "options_note": "未啟用期權分析",
            "hot_call_strikes": [],
            "hot_put_strikes": [],
            "call_put_volume_ratio": None,
            "call_put_oi_ratio": None,
            "max_pain": None,
        }

        dark_pool_data = {
            "dark_pool_score": 0,
            "dark_pool_note": "未啟用暗池/量價代理分析",
            "dark_pool_bias": "neutral",
        }

        institutional_data = {
            "institutional_score": 0,
            "institutional_note": "未啟用機構主力分析",
            "institutional_bias": "neutral",
        }

        if ENABLE_OPTIONS_FLOW and not is_tw(ticker):
            options_data = analyze_options_flow(ticker, price)

        if ENABLE_DARK_POOL:
            dark_pool_data = analyze_dark_pool(ticker, df)

        if ENABLE_INSTITUTIONAL_FLOW:
            institutional_data = analyze_institutional_flow(ticker, df, market_df)

        smart_money = build_smart_money_summary(
            options_data,
            dark_pool_data,
            institutional_data
        )

        current_position = CURRENT_POSITIONS.get(ticker, 0)

        result = analyze_stock(
            symbol=ticker,
            df=df,
            market_df=market_df,
            theme=theme,
            current_position=current_position
        )

        if result is None:
            return None

        theme_bonus = 0

        for th in themes:
            theme_bonus += THEME_BONUS.get(th, 0)

        if theme_bonus > 0:
            result["score"] += theme_bonus
            result["leader_score"] += theme_bonus * 3
            result["conditions"].append(
                f"AI基建主題加權 +{theme_bonus}：{','.join(themes)}"
            )

        smart_money_score = smart_money["smart_money_score"]

        result["score"] += smart_money_score
        result["leader_score"] += max(smart_money_score, 0) * 3

        if smart_money_score >= 6:
            result["conditions"].append("Smart Money 強烈偏多")
        elif smart_money_score >= 3:
            result["conditions"].append("Smart Money 偏多")
        elif smart_money_score <= -3:
            result["conditions"].append("Smart Money 偏空")

        if risk_mode:
            result["score"] -= 2
            result["conditions"].append("外部市場風險模式啟動")

        result["smart_money_score"] = smart_money["smart_money_score"]
        result["smart_money_bias"] = smart_money["smart_money_bias"]
        result["smart_money_note"] = smart_money["smart_money_note"]

        result["call_put_volume_ratio"] = options_data.get("call_put_volume_ratio")
        result["call_put_oi_ratio"] = options_data.get("call_put_oi_ratio")
        result["max_pain"] = options_data.get("max_pain")

        result["options_note"] = options_data.get("options_note")
        result["dark_pool_note"] = dark_pool_data.get("dark_pool_note")
        result["institutional_note"] = institutional_data.get("institutional_note")

        earnings_data = detect_earnings_risk(ticker)
        setup_grade, setup_type_note = classify_setup(result, df)
        entry_plan = build_entry_plan(result, df)

        position_data = recommend_position_size(
            setup_grade=setup_grade,
            result=result,
            earnings_data=earnings_data,
            risk_mode=risk_mode
        )

        result["retail_setup_grade"] = setup_grade
        result["setup_type_note"] = setup_type_note
        result["entry_plan"] = entry_plan
        result["position_pct"] = position_data["position_pct"]
        result["position_label"] = position_data["position_label"]
        result["earnings_risk"] = earnings_data["earnings_risk"]
        result["earnings_note"] = earnings_data["earnings_note"]

        apply_retail_edge_filters(
            result=result,
            df=df,
            risk_mode=risk_mode
        )

        if earnings_data["earnings_risk"]:
            result["score"] -= 1
            result["leader_score"] -= 3
            result["conditions"].append("財報前風險，避免重倉追價")

        if setup_grade == "S":
            result["conditions"].append("S級機構趨勢股")
        elif setup_grade == "A":
            result["conditions"].append("A級高品質突破")
        elif setup_grade == "WAIT":
            result["conditions"].append("等待回測，不建議追價")

        signal_tier_data = classify_signal_tier(
            result=result,
            df=df,
            risk_mode=risk_mode
        )

        result["signal_tier"] = signal_tier_data["signal_tier"]
        result["signal_action"] = signal_tier_data["signal_action"]

        send_signal = signal_tier_data["send_signal"]

        if force_return:
            send_signal = (
                result["score"] >= SIGNAL_SCORE_MIN
                and result["leader_score"] >= SIGNAL_LEADER_MIN
            )

        if (
            not force_return
            and result["score"] < RANKING_SCORE_MIN
            and not send_signal
        ):
            return None

        msg = format_telegram_message(result)
        msg = append_smart_money_to_message(msg, result)
        msg = append_retail_edge_to_message(msg, result)
        msg = append_signal_tier_to_message(msg, result)

        return {
            "ticker": ticker,
            "symbol": ticker,
            "score": result["score"],
            "leader_score": result["leader_score"],
            "themes": themes,
            "theme": theme,
            "message": msg,
            "send_signal": send_signal,
            "price": result.get("price", price),
            "setup_grade": result.get("setup_grade"),
            "market_regime": result.get("market_regime"),
            "smart_money_score": result.get("smart_money_score"),
            "smart_money_bias": result.get("smart_money_bias"),
            "retail_setup_grade": result.get("retail_setup_grade"),
            "setup_type_note": result.get("setup_type_note"),
            "position_pct": result.get("position_pct"),
            "position_label": result.get("position_label"),
            "entry_plan": result.get("entry_plan"),
            "earnings_risk": result.get("earnings_risk"),
            "earnings_note": result.get("earnings_note"),
            "signal_tier": result.get("signal_tier"),
            "signal_action": result.get("signal_action"),
            "breakout": result.get("breakout", False),
            "volume_ratio": result.get("volume_ratio", 1),
        }

    except Exception as e:
        print(f"{ticker} 掃描錯誤：", e)
        return None


# =========================
# 報告
# =========================

def build_close_backtest_report(market_type):
    today = now_tw().strftime("%Y-%m-%d")
    rows = []

    for _, rec in trade_recommendations.items():
        if rec["date"] != today:
            continue

        ticker = rec["ticker"]

        if market_type == "TW" and not is_tw(ticker):
            continue

        if market_type == "US" and is_tw(ticker):
            continue

        entry = rec["entry_price"]

        if not entry:
            continue

        try:
            df = download_price(ticker, "5d")

            if df.empty:
                continue

            close_price = float(df["Close"].iloc[-1])
            pnl_pct = round((close_price / entry - 1) * 100, 2)

            rows.append({
                "ticker": ticker,
                "entry": entry,
                "close": close_price,
                "pnl_pct": pnl_pct,
                "score": rec["score"],
                "leader_score": rec["leader_score"],
                "theme": ",".join(rec["themes"]),
                "smart_money_score": rec.get("smart_money_score", 0),
                "smart_money_bias": rec.get("smart_money_bias", "中性"),
            })

        except Exception as e:
            print(f"{ticker} 收盤回測錯誤：", e)

    if not rows:
        return "📌 今日收盤回測：今天沒有正式推薦訊號，無績效可統計。"

    rows = sorted(rows, key=lambda x: x["pnl_pct"], reverse=True)

    win_count = len([r for r in rows if r["pnl_pct"] > 0])
    avg_return = round(sum(r["pnl_pct"] for r in rows) / len(rows), 2)
    best = rows[0]
    worst = rows[-1]

    msg = "📊 今日推薦股收盤回測\n\n"
    msg += f"推薦數量：{len(rows)} 檔\n"
    msg += f"勝率：{win_count}/{len(rows)} = {round(win_count / len(rows) * 100, 1)}%\n"
    msg += f"平均報酬：{avg_return}%\n"
    msg += f"最佳：{best['ticker']} {best['pnl_pct']}%\n"
    msg += f"最差：{worst['ticker']} {worst['pnl_pct']}%\n\n"

    msg += "個股結果：\n"

    for r in rows:
        sign = "+" if r["pnl_pct"] > 0 else ""

        msg += (
            f"\n{r['ticker']}\n"
            f"推薦價：{round(r['entry'], 2)}\n"
            f"收盤價：{round(r['close'], 2)}\n"
            f"收盤損益：{sign}{r['pnl_pct']}%\n"
            f"Score：{r['score']} / Leader：{r['leader_score']}\n"
            f"Smart Money：{r['smart_money_score']} / {r['smart_money_bias']}\n"
            f"題材：{r['theme']}\n"
        )

    return msg


def build_ai_infra_rotation_report():
    rows = []

    for theme, tickers in THEME_GROUPS.items():
        changes = []
        leaders = []

        for ticker in tickers:
            try:
                df = download_price(ticker, "1mo")

                if df.empty or len(df) < 6:
                    continue

                close = df["Close"]
                volume = df["Volume"]

                price = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                change = (price / prev - 1) * 100

                vol20 = volume.rolling(20).mean().iloc[-1]
                vol_ratio = volume.iloc[-1] / vol20 if vol20 > 0 else 0

                changes.append(change)

                leaders.append({
                    "ticker": ticker,
                    "change": change,
                    "price": price,
                    "vol_ratio": vol_ratio,
                })

            except Exception as e:
                print(f"{ticker} AI基建輪動錯誤：", e)

        if changes:
            avg_change = sum(changes) / len(changes)
            leaders = sorted(leaders, key=lambda x: x["change"], reverse=True)

            rows.append({
                "theme": theme,
                "avg_change": avg_change,
                "leaders": leaders[:3],
            })

    if not rows:
        return "⚠️ AI基建族群輪動：資料不足"

    rows = sorted(rows, key=lambda x: x["avg_change"], reverse=True)

    msg = "🔥 AI 基建族群輪動報告\n\n"

    for i, row in enumerate(rows, 1):
        msg += f"{i}. {row['theme']}：{round(row['avg_change'], 2)}%\n"

        for leader in row["leaders"]:
            sign = "+" if leader["change"] > 0 else ""
            msg += (
                f"   - {leader['ticker']} "
                f"{sign}{round(leader['change'], 2)}% "
                f"｜量能 {round(leader['vol_ratio'], 2)}x\n"
            )

        msg += "\n"

    msg += "📌 解讀：優先觀察排名前段族群中，放量但尚未嚴重乖離20MA的個股。"

    return msg


def build_premarket_report(market_type):
    if market_type == "TW":
        benchmark = "0050.TW"
        market_name = "台股"
        universe = TW_MARKET
    else:
        benchmark = "QQQ"
        market_name = "美股"
        universe = [
            "NVDA", "AVGO", "PLTR", "CRWV", "NBIS",
            "AAOI", "LITE", "MU", "SMCI", "CLS",
            "AMD", "SOFI", "TSLA", "ARM", "MRVL",
            "HOOD", "ORCL", "APLD", "ALAB"
        ]

    try:
        df = download_price(benchmark, "6mo")

        if df.empty or len(df) < 60:
            return f"⚠️ {market_name}盤前分析：Benchmark 資料不足"

        close = df["Close"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]

        vol_ratio = round(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1], 2)

        risk_mode = market_risk_mode()

        if price > ma20 and price > ma50 and ma20 > close.rolling(20).mean().iloc[-2]:
            regime = "Risk-On / 偏多"
            strategy = "可正常掃描強勢股，但避免開盤直接追高，優先等回測不破或放量突破。"
        elif price > ma50 and price < ma20:
            regime = "震盪整理"
            strategy = "今日追價要保守，優先觀察強勢股是否回測20MA或箱型上緣不破。"
        elif price < ma50:
            regime = "Risk-Off / 偏弱"
            strategy = "今日以防守為主，降低新倉比例，避免追高高波動股。"
        else:
            regime = "中性偏多"
            strategy = "可觀察開盤後量價是否轉強，若無量突破則不急著進場。"

        if risk_mode:
            strategy += "\n⚠️ 外部市場風險模式啟動，所有新訊號建議降級處理。"

        candidates = []

        if market_type == "TW":
            scan_list = list(dict.fromkeys(AI_INFRA_THEMES + universe))[:80]
        else:
            scan_list = universe[:30]

        for ticker in scan_list:
            result = scan_stock(
                ticker=ticker,
                risk_mode=risk_mode,
                force_return=True
            )

            if result:
                candidates.append(result)

        candidates = sorted(candidates, key=lambda x: x["leader_score"], reverse=True)[:5]

        msg = f"🌅 {market_name}盤前 15 分鐘分析報告\n\n"
        msg += f"Benchmark：{benchmark}\n"
        msg += f"前收：{round(price, 2)}\n"
        msg += f"量能比：{vol_ratio}x\n\n"

        msg += "技術結構：\n"
        msg += f"5MA：{round(ma5, 2)}\n"
        msg += f"10MA：{round(ma10, 2)}\n"
        msg += f"20MA：{round(ma20, 2)}\n"
        msg += f"50MA：{round(ma50, 2)}\n\n"

        msg += f"市場狀態：{regime}\n\n"
        msg += f"📌 今日操作建議：\n{strategy}\n\n"

        if candidates:
            msg += "🔥 盤前優先觀察名單：\n"

            for i, r in enumerate(candidates, 1):
                msg += (
                    f"\n{i}. {r['ticker']}\n"
                    f"Score：{r['score']} / Leader：{r['leader_score']}\n"
                    f"Smart Money：{r.get('smart_money_score', 0)} / {r.get('smart_money_bias', '中性')}\n"
                    f"價格：{round(r.get('price', 0), 2)}\n"
                    f"題材：{','.join(r.get('themes', []))}\n"
                )
        else:
            msg += "📌 盤前沒有明顯高分候選股，建議開盤後再等量價確認。"

        return msg

    except Exception as e:
        print("build_premarket_report 錯誤：", e)
        return f"⚠️ {market_name}盤前分析產生失敗"


def build_market_close_analysis(market_type):
    if market_type == "TW":
        benchmark = "0050.TW"
        market_name = "台股"
    else:
        benchmark = "QQQ"
        market_name = "美股"

    try:
        df = download_price(benchmark, "6mo")

        if df.empty or len(df) < 60:
            return f"⚠️ {market_name}市場分析：資料不足"

        close = df["Close"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]

        day_return = round((price / prev_price - 1) * 100, 2)
        vol_ratio = round(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1], 2)

        above_ma20 = price > ma20
        above_ma50 = price > ma50
        ma20_up = ma20 > close.rolling(20).mean().iloc[-2]

        if above_ma20 and above_ma50 and ma20_up:
            regime = "偏多 / Risk-On"
            tomorrow_view = "明日偏向續強觀察，可留意強勢族群回測不破後續攻。"
        elif price < ma20 and price > ma50:
            regime = "震盪整理"
            tomorrow_view = "明日偏向區間震盪，追價需保守，優先等回測或放量突破。"
        elif price < ma50:
            regime = "偏弱 / Risk-Off"
            tomorrow_view = "明日偏向防守，降低追價，優先觀察是否跌深反彈或弱勢延續。"
        else:
            regime = "中性偏多"
            tomorrow_view = "明日可觀察是否重新站穩短均線，強勢股仍可列入追蹤。"

        msg = f"📈 {market_name}今日市場分析\n\n"
        msg += f"Benchmark：{benchmark}\n"
        msg += f"收盤：{round(price, 2)}\n"
        msg += f"日漲跌：{day_return}%\n"
        msg += f"量能比：{vol_ratio}x\n\n"

        msg += "技術結構：\n"
        msg += f"5MA：{round(ma5, 2)}\n"
        msg += f"10MA：{round(ma10, 2)}\n"
        msg += f"20MA：{round(ma20, 2)}\n"
        msg += f"50MA：{round(ma50, 2)}\n\n"

        msg += f"市場狀態：{regime}\n\n"
        msg += f"🔮 明日市場預期：\n{tomorrow_view}"

        return msg

    except Exception as e:
        print("build_market_close_analysis 錯誤：", e)
        return f"⚠️ {market_name}市場分析產生失敗"


def should_send_premarket_report(market_type):
    global last_premarket_report_date

    n = now_tw()
    today = n.strftime("%Y-%m-%d")
    minutes = n.hour * 60 + n.minute
    key = f"{today}-{market_type}"

    if last_premarket_report_date == key:
        return False

    if market_type == "TW":
        if n.weekday() >= 5:
            return False

        return TW_PREMARKET_REPORT_TIME <= minutes < 9 * 60

    if market_type == "US":
        if n.weekday() > 4:
            return False

        return US_PREMARKET_REPORT_TIME <= minutes < 21 * 60 + 30

    return False


def send_premarket_report_if_needed(market_type):
    global last_premarket_report_date

    today = now_tw().strftime("%Y-%m-%d")
    key = f"{today}-{market_type}"

    if should_send_premarket_report(market_type):
        msg = build_premarket_report(market_type)
        send_telegram_once(msg)
        last_premarket_report_date = key


def send_ai_infra_report_if_needed():
    global last_ai_infra_report_date

    n = now_tw()
    today = n.strftime("%Y-%m-%d")
    minutes = n.hour * 60 + n.minute

    if last_ai_infra_report_date == today:
        return

    if n.weekday() >= 5:
        return

    if 8 * 60 + 45 <= minutes < 9 * 60:
        msg = build_ai_infra_rotation_report()
        send_telegram_once(msg)
        last_ai_infra_report_date = today


def should_send_close_report(market_type):
    global last_close_report_date

    n = now_tw()
    today = n.strftime("%Y-%m-%d")
    minutes = n.hour * 60 + n.minute
    key = f"{today}-{market_type}"

    if last_close_report_date == key:
        return False

    if market_type == "TW":
        if n.weekday() >= 5:
            return False

        return minutes >= TW_CLOSE_REPORT_TIME

    if market_type == "US":
        return 5 * 60 + 10 <= minutes <= 8 * 60

    return False


def send_close_report_if_needed(market_type):
    global last_close_report_date

    today = now_tw().strftime("%Y-%m-%d")
    key = f"{today}-{market_type}"

    if should_send_close_report(market_type):
        backtest_msg = build_close_backtest_report(market_type)
        analysis_msg = build_market_close_analysis(market_type)

        send_telegram_once(backtest_msg)
        send_telegram_once(analysis_msg)

        last_close_report_date = key


# =========================
# 最終強勢股摘要
# =========================

def send_summary_report(signal_results):
    if not signal_results:
        return

    sorted_results = sorted(
        signal_results,
        key=lambda x: (
            x.get("score", 0),
            x.get("leader_score", 0)
        ),
        reverse=True
    )

    lines = []
    lines.append("🔥 今日強勢股總覽")
    lines.append("")

    for idx, r in enumerate(sorted_results[:15], start=1):
        symbol = r.get("ticker") or r.get("symbol", "N/A")
        theme = ",".join(r.get("themes", [])) or r.get("theme", "")
        score = r.get("score", 0)
        leader = r.get("leader_score", 0)
        tier = r.get("signal_tier", "N/A")

        lines.append(
            f"{idx}. {symbol}  Score:{score} / Leader:{leader}  Tier:{tier}  {theme}"
        )

    msg = "\n".join(lines)
    send_telegram_once(msg)


# =========================
# Trading Leaderboard
# =========================

def build_trading_leaderboard(signal_results):
    if not signal_results:
        return ""

    s_rank = []
    a_rank = []
    b_rank = []

    for r in signal_results:
        symbol = r.get("ticker") or r.get("symbol", "")
        score = r.get("score", 0)
        leader = r.get("leader_score", 0)
        tier = r.get("signal_tier", "")
        setup = r.get("retail_setup_grade", "")

        if tier == "S" or setup == "S" or (score >= 12 and leader >= 45):
            s_rank.append(symbol)
        elif tier == "A" or setup == "A" or (score >= 10 and leader >= 35):
            a_rank.append(symbol)
        elif score >= 7:
            b_rank.append(symbol)

    msg = "🏆 Trading Leaderboard\n\n"

    msg += "🟢 S級（可直接考慮）\n"
    if s_rank:
        for s in s_rank[:10]:
            msg += f"• {s}\n"
    else:
        msg += "無\n"

    msg += "\n🟡 A級（等回測）\n"
    if a_rank:
        for s in a_rank[:15]:
            msg += f"• {s}\n"
    else:
        msg += "無\n"

    msg += "\n🔴 B級（觀察）\n"
    if b_rank:
        for s in b_rank[:15]:
            msg += f"• {s}\n"
    else:
        msg += "無\n"

    return msg


def build_pure_ranking_report(results, market_type, top_n=20):
    if not results:
        return ""

    market_name = "台股" if market_type == "TW" else "美股"
    rows = sorted(results, key=lambda x: x.get("leader_score", 0), reverse=True)[:top_n]

    msg = f"🏆 {market_name}純排名 Top {top_n}\n\n"

    for i, r in enumerate(rows, 1):
        msg += (
            f"{i}. {r.get('ticker')}\n"
            f"Score：{r.get('score', 0)}｜Leader：{r.get('leader_score', 0)}\n"
            f"Tier：{r.get('signal_tier', 'N/A')}｜Setup：{r.get('retail_setup_grade', 'N/A')}\n"
            f"Smart Money：{r.get('smart_money_score', 0)} / {r.get('smart_money_bias', '中性')}\n"
            f"建議倉位：{r.get('position_pct', 0)}%｜{r.get('position_label', 'N/A')}\n"
            f"題材：{','.join(r.get('themes', []))}\n\n"
        )

    msg += "📌 這是純排名，不代表全部都是正式買進訊號。正式推薦仍以 S / A 級與通知原因為準。"

    return msg


# =========================
# 測試選股
# =========================

def run_test_mode():
    test_tickers = [
        "NVDA", "AVGO", "PLTR", "CRWV", "NBIS",
        "AAOI", "LITE", "MU", "SMCI", "CLS",
        "AMD", "SOFI", "TSLA", "ARM", "MRVL",
        "2330.TW", "2317.TW", "2382.TW", "6669.TW",
        "3017.TW", "3037.TW", "2308.TW", "3231.TW",
        "2368.TW", "3443.TW", "4908.TW", "3450.TW",
        "4979.TW", "2408.TW", "8299.TW", "1519.TW",
        "1503.TW", "1513.TW", "3324.TW", "3653.TW",
        "2049.TW", "2634.TW", "8222.TW", "2345.TW",
        "3583.TW", "3131.TW", "5443.TW", "2467.TW",
        "6187.TW", "6640.TW",
        "2404.TW", "6196.TW", "5536.TW", "6691.TW",
        "6139.TW", "6667.TW",
        "3189.TW", "8046.TW", "3163.TW", "3363.TW",
    ]

    send_telegram("🧪 測試選股模式啟動")
    ai_rotation_msg = build_ai_infra_rotation_report()
    send_telegram_once(ai_rotation_msg)
    test_results = []
    risk_mode = market_risk_mode()

    for ticker in test_tickers:
        result = scan_stock(
            ticker=ticker,
            risk_mode=risk_mode,
            force_return=True
        )

        if result:
            test_results.append(result)
            print(
                ticker,
                "Score:",
                result["score"],
                "Leader:",
                result["leader_score"],
                "Smart:",
                result.get("smart_money_score"),
                "Signal:",
                result["send_signal"]
            )
        else:
            print(f"{ticker} 無法取得資料或被基本過濾")

    test_results = sorted(
        test_results,
        key=lambda x: x["leader_score"],
        reverse=True
    )

    if test_results:
        rotation_msg = build_sector_rotation(test_results)
        leaderboard_msg = build_leaderboard(test_results, top_n=15)
        pure_ranking_msg = build_pure_ranking_report(test_results, "TEST", top_n=20)

        if rotation_msg:
            send_telegram_once(rotation_msg)

        if leaderboard_msg:
            send_telegram_once(leaderboard_msg)

        if pure_ranking_msg:
            send_telegram_once(pure_ranking_msg)

        signal_results = [
            r for r in test_results
            if r["send_signal"]
        ]

        if signal_results:
            send_telegram_once(
                f"🔥 測試中共有 {len(signal_results)} 檔達正式訊號門檻"
            )

            for r in signal_results[:10]:
                send_telegram_once(r["message"])

            send_summary_report(signal_results)
            leaderboard_msg = build_trading_leaderboard(signal_results)

            if leaderboard_msg:
                send_telegram_once(leaderboard_msg)
        else:
            send_telegram_once(
                "📌 測試結果：目前沒有股票達正式訊號門檻，但已產生評分與排名"
            )

    else:
        send_telegram_once("⚠️ 測試結果：沒有任何股票可評分")

    send_telegram_once("🧪 測試選股模式結束")


# =========================
# 主程式
# =========================

if TEST_MODE:
    run_test_mode()
    exit()


send_telegram_once("🚀 v16 Institutional Alpha Engine 已啟動")

US_MARKET = get_us_market()
TW_MARKET = get_tw_market()


def get_active_universe():
    n = now_tw()
    minutes = n.hour * 60 + n.minute

    tw_open = (
        n.weekday() < 5
        and 9 * 60 <= minutes <= 13 * 60 + 30
    )

    us_open = (
        (minutes >= 21 * 60 + 30 and n.weekday() <= 4)
        or
        (minutes <= 4 * 60 and 1 <= n.weekday() <= 5)
    )

    if tw_open:
        return TW_MARKET, "TW"

    if us_open:
        return US_MARKET, "US"

    return [], None


if not US_MARKET and not TW_MARKET:
    send_telegram_once("⚠️ 股票池抓取失敗，請檢查資料來源")


while True:
    try:
        send_close_report_if_needed("TW")
        send_close_report_if_needed("US")

        send_premarket_report_if_needed("TW")
        send_premarket_report_if_needed("US")
        send_ai_infra_report_if_needed()

        risk_mode = market_risk_mode()

        market_universe, market_type = get_active_universe()

        if not market_universe:
            print("目前非台股 / 美股開盤時間")
            time.sleep(SCAN_INTERVAL)
            continue

        if market_type == "TW":
            batch = TW_MARKET
        else:
            start = scan_pointer
            end = start + MAX_SCAN_PER_ROUND
            batch = market_universe[start:end]
            scan_pointer = end

            if scan_pointer >= len(market_universe):
                scan_pointer = 0

        # =========================
        # 持倉管理
        # =========================

        if mark_once_interval(f"{market_type}_portfolio_report", PORTFOLIO_REPORT_INTERVAL_MINUTES):
            try:
                risk_report = portfolio_risk_report()

                if risk_report:
                    send_telegram_once(risk_report)

            except Exception as e:
                print("portfolio_risk_report 錯誤：", e)

            try:
                position_msgs = manage_positions()

                for msg in position_msgs:
                    send_telegram_once(msg)

            except Exception as e:
                print("manage_positions 錯誤：", e)

        # =========================
        # 市場掃描
        # =========================

        results = []

        for ticker in batch:
            if not market_open_for(ticker):
                continue

            result = scan_stock(
                ticker=ticker,
                risk_mode=risk_mode,
                force_return=False
            )

            if result:
                results.append(result)

        results = sorted(
            results,
            key=lambda x: x["leader_score"],
            reverse=True
        )

        # =========================
        # Leaderboard / Sector Rotation / 純排名
        # =========================

        signal_results = []

        if results:
            if mark_once_interval(f"{market_type}_rotation", ROTATION_INTERVAL_MINUTES):
                rotation_msg = build_sector_rotation(results)
                if rotation_msg:
                    send_telegram_once(rotation_msg)

            if mark_once_interval(f"{market_type}_leaderboard", PURE_RANKING_INTERVAL_MINUTES):
                leaderboard_msg = build_leaderboard(results, top_n=10)
                if leaderboard_msg:
                    send_telegram_once(leaderboard_msg)

            if mark_once_interval(f"{market_type}_pure_ranking", PURE_RANKING_INTERVAL_MINUTES):
                pure_ranking_msg = build_pure_ranking_report(results, market_type, top_n=20)
                if pure_ranking_msg:
                    send_telegram_once(pure_ranking_msg)

            if risk_mode:
                send_telegram_once("⚠️ 市場風險模式啟動，所有訊號降級處理")

            signal_results = [
                r for r in results
                if r["send_signal"]
            ]

            if mark_once_interval(f"{market_type}_scan_count", SUMMARY_INTERVAL_MINUTES):
                send_telegram_once(
                    f"🔥 本輪評分 {len(results)} 檔，其中 {len(signal_results)} 檔達正式訊號門檻"
                )

            for r in signal_results[:10]:
                send_it, reason = should_send_signal(r)

                if send_it:
                    record_recommendation(r)
                    upgrade_note = f"\n\n📌 通知原因：{reason}"
                    send_telegram(r["message"] + upgrade_note)

            if signal_results and mark_once_interval(f"{market_type}_summary", SUMMARY_INTERVAL_MINUTES):
                send_summary_report(signal_results)

                trading_leaderboard_msg = build_trading_leaderboard(signal_results)
                if trading_leaderboard_msg:
                    send_telegram_once(trading_leaderboard_msg)

        else:
            print("本輪沒有可排名股票")

        if len(sent_today) > 1000:
            sent_today.clear()

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print("主程式錯誤：", e)
        time.sleep(60)