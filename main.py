import os
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from position_manager import manage_positions
from portfolio_engine import portfolio_risk_report
from analysis_engine import analyze_stock, format_telegram_message
from leaderboard_engine import build_leaderboard, build_sector_rotation
from scanner_state import load_state, save_state
from dynamic_priority import format_change_message, refresh_dynamic_state
from market_universe import (
    TW_PRIORITY,
    US_PRIORITY,
    advance_cursor,
    get_tw_market as load_tw_market,
    get_us_market as load_us_market,
    make_batch,
)


# =========================
# Telegram
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# =========================
# Config
# =========================

SCAN_INTERVAL = 300
US_BATCH_SIZE = int(os.getenv("US_BATCH_SIZE", "20"))
TW_BATCH_SIZE = int(os.getenv("TW_BATCH_SIZE", "30"))
MAX_RUN_SECONDS = int(os.getenv("MAX_RUN_SECONDS", "720"))
FINISH_RESERVE_SECONDS = 90

SIGNAL_SCORE_MIN = 8
SIGNAL_LEADER_MIN = 30
RANKING_SCORE_MIN = 0

TEST_MODE = False

ENABLE_OPTIONS_FLOW = True
ENABLE_DARK_POOL = True
ENABLE_INSTITUTIONAL_FLOW = True

# 沒有暗池 API 就留空，系統會自動使用量價代理模型
DARK_POOL_API_KEY = ""

sent_today = set()
signal_state = {}
sent_msg_cache = set()
trade_recommendations = {}

us_scan_cursor = 0
tw_scan_cursor = 0
last_close_report_date = None
last_premarket_report_date = None
last_ai_infra_report_date = None
dynamic_priority_state = {}
latest_scan_results = []
notification_history = []
scanner_health = {
    "status": "尚未執行",
    "telegram_ok": None,
    "telegram_sent": 0,
    "telegram_failed": 0,
    "state_saved": False,
}

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
# Taiwan Stock Universe
# =========================

TW_CORE = [
    "2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW",
    "2412.TW", "2881.TW", "2882.TW", "2884.TW", "2885.TW",
    "2891.TW", "2892.TW", "1301.TW", "1303.TW", "2002.TW",
    "2303.TW", "2379.TW", "3711.TW", "2357.TW", "2356.TW",
    "2327.TW", "3034.TW", "3008.TW", "2395.TW", "2207.TW",
]

TW_GROWTH = [
    # AI Server / 組裝 / 散熱 / 電源
    "2356.TW", "2382.TW", "3231.TW", "6669.TW", "3017.TW",
    "3324.TW", "3653.TW", "6805.TW", "8996.TW", "2308.TW",

    # PCB / CCL / ABF
    "2383.TW", "3037.TW", "8046.TW", "3189.TW", "2368.TW",
    "2313.TW", "6274.TW", "8358.TW", "8213.TW",

    # 光通訊 / CPO / 網通
    "4979.TW", "3450.TW", "3081.TWO", "3363.TW", "4908.TW",
    "2345.TW", "6285.TW", "6530.TW",

    # 先進封裝 / 半導體設備 / 測試
    "6223.TW", "6510.TW", "3131.TW", "3583.TW", "6196.TW",
    "6438.TW", "6187.TW", "6667.TW", "6789.TW",

    # 記憶體 / IC Design
    "2408.TW", "2344.TW", "3006.TW", "3443.TW", "3035.TW",
    "6533.TW", "3661.TW", "5274.TW",

    # 機器人 / 工業自動化 / 軍工
    "2049.TW", "1590.TW", "4572.TW", "2465.TW", "2634.TW",
    "8033.TW", "8222.TW",
]

TW_MARKET = list(dict.fromkeys(TW_CORE + TW_GROWTH))

# =========================
# Emergency Stop Loss Alert
# =========================

ENABLE_EMERGENCY_STOP = True

EMERGENCY_COOLDOWN_MINUTES = 60   # 緊急通知至少間隔 60 分鐘
last_emergency_alert_time = None

# =========================
# Retail Edge / 少盯盤模式
# =========================

RETAIL_EDGE_MODE = True

MAX_CHASE_ABOVE_MA20 = 1.12
EXTREME_CHASE_ABOVE_MA20 = 1.18

MIN_SMART_MONEY_FOR_SIGNAL = 2
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
S_SMART_MONEY_MIN = 4

A_SIGNAL_SCORE_MIN = 10
A_LEADER_SCORE_MIN = 35
A_SMART_MONEY_MIN = 2

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
    "AI基建": [
    "gpu",
    "data center",
    "ai server",
    "server rack",
    "cloud computing",
    "hyperscaler",
    "nvidia",
    "training cluster",
    "inference",
    "blackwell",
    "h100"
],
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
    global scanner_health, notification_history
    if not msg:
        return False

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram 環境變數尚未設定，訊息未發送：")
        print(str(msg)[:800])
        scanner_health["telegram_ok"] = False
        scanner_health["telegram_failed"] = scanner_health.get("telegram_failed", 0) + 1
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    chunks = [
        msg[i:i + 3500]
        for i in range(0, len(msg), 3500)
    ]

    succeeded = True
    for chunk in chunks:
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": chunk
                },
                timeout=10
            )
            response.raise_for_status()
        except Exception as e:
            # Do not print the request URL because it contains the bot token.
            print("Telegram 發送失敗：", type(e).__name__)
            succeeded = False

    scanner_health["telegram_ok"] = succeeded
    counter = "telegram_sent" if succeeded else "telegram_failed"
    scanner_health[counter] = scanner_health.get(counter, 0) + 1
    notification_history.insert(0, {
        "sent_at": now_tw().isoformat(timespec="seconds"),
        "status": "成功" if succeeded else "失敗",
        "summary": str(msg).strip().splitlines()[0][:120],
    })
    del notification_history[50:]
    return succeeded


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
    return market_is_open("TW" if is_tw(ticker) else "US")


def market_is_open(market_type, moment=None):
    """Check regular local session hours, including US daylight-saving changes."""
    zone = ZoneInfo("Asia/Taipei" if market_type == "TW" else "America/New_York")
    current = datetime.now(tz=ZoneInfo("UTC")) if moment is None else moment
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("UTC"))
    local = current.astimezone(zone)
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5:
        return False
    if market_type == "TW":
        return 9 * 60 <= minute <= 13 * 60 + 30
    return 9 * 60 + 30 <= minute <= 16 * 60


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


def passes_liquidity_filter(ticker, df):
    """Apply market-specific price and 20-session average-volume floors."""
    if df.empty or len(df) < 20:
        return False
    price = float(df["Close"].iloc[-1])
    avg_volume = float(df["Volume"].tail(20).mean())
    if is_tw(ticker):
        return price >= 10 and avg_volume >= 100000
    return price >= 5 and avg_volume >= 500000


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

def emergency_market_stop_check(market_type):
    """
    市場苗頭不對時，發出緊急停損 / 降風險通知
    """

    global last_emergency_alert_time

    if not ENABLE_EMERGENCY_STOP:
        return

    now = datetime.now()

    if last_emergency_alert_time:
        diff = (now - last_emergency_alert_time).total_seconds() / 60
        if diff < EMERGENCY_COOLDOWN_MINUTES:
            return

    if market_type == "TW":
        index_symbol = "0050.TW"
        market_name = "台股"
    else:
        index_symbol = "QQQ"
        market_name = "美股"

    try:
        df = yf.download(index_symbol, period="6mo", interval="1d", progress=False)

        if df.empty or len(df) < 60:
            return

        close = df["Close"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        ma5 = float(close.rolling(5).mean().iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])

        vol_ratio = float(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1])
        daily_drop = (price - prev_price) / prev_price * 100

        danger_score = 0
        reasons = []

        if daily_drop <= -2.0:
            danger_score += 2
            reasons.append(f"大盤單日急跌 {daily_drop:.2f}%")

        if price < ma20:
            danger_score += 1
            reasons.append("跌破 20MA")

        if price < ma50:
            danger_score += 2
            reasons.append("跌破 50MA")

        if ma5 < ma20:
            danger_score += 1
            reasons.append("5MA 跌破 20MA，短線轉弱")

        if vol_ratio >= 1.5 and daily_drop < 0:
            danger_score += 2
            reasons.append(f"放量下跌，成交量 {vol_ratio:.2f} 倍")

        if danger_score >= 4:
            msg = f"""
🚨 緊急風險通知｜{market_name}

市場苗頭不對，建議立即降低風險。

追蹤標的：{index_symbol}
目前價格：{price:.2f}
今日漲跌：{daily_drop:.2f}%

風險分數：{danger_score}/8

觸發原因：
{chr(10).join(['⚠️ ' + r for r in reasons])}

建議動作：
1. 停止追高與新增部位
2. 砍掉跌破停損的弱勢股
3. 高波動小型股先降倉
4. 已獲利股票可先部分停利
5. 不要攤平破線股
6. 等大盤重新站回 20MA 再恢復積極操作

這不是叫你無腦全砍，而是進入保護本金模式。
"""

            send_telegram(msg)
            last_emergency_alert_time = now

    except Exception as e:
        print("emergency_market_stop_check 錯誤：", e)

# =========================
# 全市場股票池
# =========================

def get_us_fallback():

    fallback = [
        # AI / Mega Cap
        "NVDA", "AVGO", "AMD", "ARM", "MSFT", "GOOGL", "AMZN", "META", "AAPL", "ORCL",

        # 記憶體 / Storage / HBM
        "MU", "WDC", "STX", "SNDK", "MRVL", "MCHP", "NXPI",

        # 先進封裝 / OSAT / Substrate
        "AMKR", "ASX", "TTMI", "SANM", "JBL", "COHU",

        # 半導體設備
        "ASML", "AMAT", "LRCX", "KLAC", "TEL", "TER", "ACLS", "ICHR", "UCTT",

        # 檢測 / 量測 / EDA
        "ONTO", "MKSI", "AEHR", "FORM", "COHR", "KEYS", "SNPS", "CDNS",

        # 光通訊 / CPO
        "AAOI", "LITE", "FN", "CIEN", "NOK", "GLW",

        # AI Infra / Data Center
        "CRWV", "NBIS", "APLD", "IREN", "CORZ", "CLS", "DELL", "HPE", "SMCI",

        # 國防 / 無人機 / 太空
        "KTOS", "AVAV", "ONDS", "ASTS", "LUNR", "RKLB",

        # Fintech / Crypto beta
        "SOFI", "HOOD", "COIN", "MSTR",

        # 電力 / 核能
        "OKLO", "SMR", "CEG", "VST", "GEV",

    ]

    return fallback

def get_tw_fallback():
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

    all_tickers = tw50 + ai_growth + AI_INFRA_THEMES

    return list(dict.fromkeys(all_tickers))


# =========================
# Theme 判定
# =========================

EXCLUDED_SECTORS = [
    "bank",
    "financial",
    "insurance",
    "asset management",
    "capital markets"
]


def detect_themes(*texts):
    """Detect themes from every available text source for a ticker.

    The scanner supplies both the ticker and Yahoo's business summary.  Accepting
    all text fragments keeps that call safe and also lets the summary provide the
    keyword matches needed by sector rotation.
    """

    text = " ".join(str(value) for value in texts if value is not None).lower()

    # =========================
    # 排除金融股
    # =========================

    if any(x in text for x in EXCLUDED_SECTORS):
        return []

    detected = []

    # =========================
    # 主題偵測
    # =========================

    for theme, keywords in THEME_KEYWORDS.items():

        score = 0

        for k in keywords:

            if k.lower() in text:
                score += 1

        # 至少命中兩個關鍵字才算
        if score >= 2:
            detected.append(theme)

    return detected


def primary_theme(themes):
    """Return the leading detected theme with a safe market-wide fallback."""
    return themes[0] if themes else "一般市場股"


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
        "signal_tier": result.get("signal_tier", ""),
        "signal_action": result.get("signal_action", ""),
        "position_pct": result.get("position_pct", 0),
        "position_label": result.get("position_label", ""),
        "market_regime": result.get("market_regime", ""),
        "earnings_note": result.get("earnings_note", ""),
        "conditions": list(result.get("conditions", []))[:8],
        "entry_plan": result.get("entry_plan", {}),
        "price_source": result.get("price_source", "Yahoo Finance"),
        "price_updated_at": result.get("price_updated_at"),
        "catalyst": result.get("catalyst", ""),
        "catalysts": list(result.get("catalysts", []))[:6],
        "headlines": list(result.get("headlines", []))[:5],
        "outcome": {
            "status": "追蹤中", "current_price": result.get("price", 0),
            "current_return_pct": 0, "highest_price": result.get("price", 0),
            "highest_gain_pct": 0, "stop_hit": False,
            "target_1_hit": False, "target_2_hit": False,
            "updated_at": result.get("price_updated_at"),
        },
    }


def update_recommendation_outcomes(ticker, df):
    """Update persisted signal outcomes whenever a ticker receives a fresh quote."""
    if df.empty:
        return
    updated_at = pd.Timestamp(df.index[-1]).isoformat()
    current = float(df["Close"].iloc[-1])
    for record in trade_recommendations.values():
        if record.get("ticker") != ticker or not record.get("entry_price"):
            continue
        try:
            start = pd.Timestamp(record["date"])
            index = pd.to_datetime(df.index)
            history = df.loc[index >= start]
            if history.empty:
                history = df.tail(1)
            entry = float(record["entry_price"])
            highest = float(history["High"].max())
            lowest = float(history["Low"].min())
            plan = record.get("entry_plan") or {}
            stop = float(plan.get("stop_loss") or 0)
            target_1 = float(plan.get("target_1") or 0)
            target_2 = float(plan.get("target_2") or 0)
            stop_hit = bool(stop and lowest <= stop)
            target_1_hit = bool(target_1 and highest >= target_1)
            target_2_hit = bool(target_2 and highest >= target_2)
            status = "停損" if stop_hit else "第二目標達標" if target_2_hit else "第一目標達標" if target_1_hit else "追蹤中"
            record["outcome"] = {
                "status": status, "current_price": round(current, 2),
                "current_return_pct": round((current / entry - 1) * 100, 2),
                "highest_price": round(highest, 2),
                "highest_gain_pct": round((highest / entry - 1) * 100, 2),
                "stop_hit": stop_hit, "target_1_hit": target_1_hit,
                "target_2_hit": target_2_hit, "updated_at": updated_at,
            }
        except (KeyError, TypeError, ValueError):
            continue


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

    risk = max(price - stop, 0)
    target_1 = price + risk
    target_2 = price + risk * 2
    rr_ratio = (target_2 - price) / risk if risk else 0

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
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
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
        price_updated_at = pd.Timestamp(df.index[-1]).isoformat()
        update_recommendation_outcomes(ticker, df)

        if not passes_liquidity_filter(ticker, df):
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
            "conditions": list(result.get("conditions", []))[:8],
            "price_source": "Yahoo Finance",
            "price_updated_at": price_updated_at,
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

US_MARKET = []
TW_MARKET = []


def get_active_universe():
    if market_is_open("TW"):
        return TW_MARKET, "TW"

    if market_is_open("US"):
        return US_MARKET, "US"

    return [], None


def restore_scan_state(state_path):
    """Restore the small amount of state needed between one-shot runs."""
    global sent_today, signal_state, sent_msg_cache, trade_recommendations
    global us_scan_cursor, tw_scan_cursor, last_close_report_date, last_premarket_report_date
    global last_ai_infra_report_date, last_emergency_alert_time, dynamic_priority_state
    global latest_scan_results, notification_history, scanner_health

    state = load_state(state_path)
    sent_today = set(state.get("sent_today", []))
    signal_state = state.get("signal_state", {})
    sent_msg_cache = set(state.get("sent_msg_cache", []))
    trade_recommendations = state.get("trade_recommendations", {})
    # Read the v1 cursor for a seamless upgrade, then keep independent market cursors.
    us_scan_cursor = int(state.get("us_scan_cursor", state.get("scan_pointer", 0)))
    tw_scan_cursor = int(state.get("tw_scan_cursor", 0))
    last_close_report_date = state.get("last_close_report_date")
    last_premarket_report_date = state.get("last_premarket_report_date")
    last_ai_infra_report_date = state.get("last_ai_infra_report_date")
    dynamic_priority_state = {
        "dynamic_us_priority": state.get("dynamic_us_priority", []),
        "dynamic_tw_priority": state.get("dynamic_tw_priority", []),
        "last_dynamic_update": state.get("last_dynamic_update"),
    }
    latest_scan_results = state.get("latest_scan_results", [])
    notification_history = state.get("notification_history", [])
    scanner_health = state.get("scanner_health", scanner_health)

    emergency_time = state.get("last_emergency_alert_time")
    last_emergency_alert_time = (
        datetime.fromisoformat(emergency_time) if emergency_time else None
    )


def persist_scan_state(state_path):
    """Atomically persist notification throttles and both market batch cursors."""
    state = {
        "sent_today": sorted(sent_today),
        "signal_state": signal_state,
        "sent_msg_cache": sorted(sent_msg_cache),
        "trade_recommendations": trade_recommendations,
        "us_scan_cursor": us_scan_cursor,
        "tw_scan_cursor": tw_scan_cursor,
        "last_close_report_date": last_close_report_date,
        "last_premarket_report_date": last_premarket_report_date,
        "last_ai_infra_report_date": last_ai_infra_report_date,
        "dynamic_us_priority": dynamic_priority_state.get("dynamic_us_priority", []),
        "dynamic_tw_priority": dynamic_priority_state.get("dynamic_tw_priority", []),
        "last_dynamic_update": dynamic_priority_state.get("last_dynamic_update"),
        "latest_scan_results": latest_scan_results,
        "notification_history": notification_history[:50],
        "scanner_health": scanner_health,
        "last_emergency_alert_time": (
            last_emergency_alert_time.isoformat()
            if last_emergency_alert_time else None
        ),
    }
    save_state(state_path, state)


def run_scan_once(deadline=None):
    """Run one scheduled scan and return instead of acting as a daemon."""
    global us_scan_cursor, tw_scan_cursor, dynamic_priority_state
    global latest_scan_results, scanner_health
    deadline = deadline if deadline is not None else time.monotonic() + MAX_RUN_SECONDS

    send_close_report_if_needed("TW")
    send_close_report_if_needed("US")

    send_premarket_report_if_needed("TW")
    send_premarket_report_if_needed("US")
    send_ai_infra_report_if_needed()

    market_universe, market_type = get_active_universe()
    if not market_universe:
        print("目前非台股 / 美股開盤時間")
        scanner_health.update({"status": "休市", "active_market": None,
                               "requested": 0, "completed": 0,
                               "ranked": 0, "signals": 0})
        return

    dynamic_us = dynamic_priority_state.get("dynamic_us_priority", [])
    dynamic_tw = dynamic_priority_state.get("dynamic_tw_priority", [])
    dynamic_by_symbol = {
        row.get("symbol"): row for row in dynamic_us + dynamic_tw
        if isinstance(row, dict) and row.get("symbol")
    }

    risk_mode = market_risk_mode()

    try:
        emergency_market_stop_check(market_type)
    except Exception as e:
        print("emergency_market_stop_check 錯誤：", e)

    if market_type == "TW":
        start = tw_scan_cursor
        batch, market_slice = make_batch(
            market_universe, tw_scan_cursor, TW_BATCH_SIZE, TW_PRIORITY,
            [row["symbol"] for row in dynamic_tw],
        )
    else:
        start = us_scan_cursor
        batch, market_slice = make_batch(
            market_universe, us_scan_cursor, US_BATCH_SIZE, US_PRIORITY,
            [row["symbol"] for row in dynamic_us],
        )

    scanner_health.update({"status": "掃描中", "active_market": market_type,
                           "universe_size": len(market_universe),
                           "requested": len(batch), "completed": 0,
                           "ranked": 0, "signals": 0, "start_cursor": start})

    if mark_once_interval(f"{market_type}_scan_start", 30):
        send_telegram_once(
            f"{market_type} 分批掃描啟動\n"
            f"股票池：{len(market_universe)} 檔\n"
            f"本輪：{len(batch)} 檔（含每輪優先股）\n"
            f"起始游標：{start}"
        )

    if mark_once_interval(
        f"{market_type}_portfolio_report", PORTFOLIO_REPORT_INTERVAL_MINUTES
    ):
        try:
            risk_report = portfolio_risk_report()
            if risk_report:
                send_telegram_once(risk_report)
        except Exception as e:
            print("portfolio_risk_report 錯誤：", e)

        try:
            for msg in manage_positions():
                send_telegram_once(msg)
        except Exception as e:
            print("manage_positions 錯誤：", e)

    results = []
    completed_tickers = set()
    try:
        for ticker in batch:
            if time.monotonic() >= deadline:
                print("已達本輪時間上限，保存游標後結束")
                break
            if market_open_for(ticker):
                result = scan_stock(ticker=ticker, risk_mode=risk_mode, force_return=False)
                if result:
                    dynamic = dynamic_by_symbol.get(ticker, {})
                    result["catalyst"] = dynamic.get("catalyst", "")
                    result["catalysts"] = list(dynamic.get("catalysts", []))[:6]
                    result["headlines"] = list(dynamic.get("headlines", []))[:5]
                    results.append(result)
                completed_tickers.add(ticker)
    finally:
        next_cursor = advance_cursor(
            market_universe, start, market_slice, completed_tickers
        )
        if market_type == "TW":
            tw_scan_cursor = next_cursor
        else:
            us_scan_cursor = next_cursor
        scanner_health["completed"] = len(completed_tickers)
        scanner_health["next_cursor"] = next_cursor

    results.sort(key=lambda x: x["leader_score"], reverse=True)
    latest_scan_results = [{
        "ticker": row.get("ticker"),
        "price": row.get("price"),
        "score": row.get("score"),
        "leader_score": row.get("leader_score"),
        "themes": list(row.get("themes", []))[:5],
        "conditions": list(row.get("conditions", []))[:8],
        "signal_tier": row.get("signal_tier"),
        "signal_action": row.get("signal_action"),
        "send_signal": bool(row.get("send_signal")),
        "position_pct": row.get("position_pct"),
        "position_label": row.get("position_label"),
        "market_regime": row.get("market_regime"),
        "smart_money_bias": row.get("smart_money_bias"),
        "earnings_note": row.get("earnings_note"),
        "entry_plan": row.get("entry_plan", {}),
        "price_source": row.get("price_source", "Yahoo Finance"),
        "price_updated_at": row.get("price_updated_at"),
        "catalyst": row.get("catalyst", ""),
        "catalysts": list(row.get("catalysts", []))[:6],
        "headlines": list(row.get("headlines", []))[:5],
    } for row in results[:40]]
    scanner_health["ranked"] = len(results)
    if not results:
        print("本輪沒有可排名股票")
        scanner_health["status"] = "完成（無符合評分標的）"
        return

    if mark_once_interval(f"{market_type}_rotation", ROTATION_INTERVAL_MINUTES):
        rotation_msg = build_sector_rotation(results)
        if rotation_msg:
            send_telegram_once(rotation_msg)

    if mark_once_interval(f"{market_type}_leaderboard", PURE_RANKING_INTERVAL_MINUTES):
        leaderboard_msg = build_leaderboard(results, top_n=10)
        if leaderboard_msg:
            send_telegram_once(leaderboard_msg)

    if mark_once_interval(f"{market_type}_pure_ranking", PURE_RANKING_INTERVAL_MINUTES):
        ranking_msg = build_pure_ranking_report(results, market_type, top_n=20)
        if ranking_msg:
            send_telegram_once(ranking_msg)

    if risk_mode:
        send_telegram_once("⚠️ 市場風險模式啟動，所有訊號降級處理")

    signal_results = [r for r in results if r["send_signal"]]
    scanner_health["signals"] = len(signal_results)
    scanner_health["status"] = "完成"
    if mark_once_interval(f"{market_type}_scan_count", SUMMARY_INTERVAL_MINUTES):
        send_telegram_once(
            f"🔥 本輪評分 {len(results)} 檔，其中 {len(signal_results)} 檔達正式訊號門檻"
        )

    for result in signal_results[:10]:
        send_it, reason = should_send_signal(result)
        if send_it:
            record_recommendation(result)
            send_telegram(result["message"] + f"\n\n📌 通知原因：{reason}")

    if signal_results and mark_once_interval(f"{market_type}_summary", SUMMARY_INTERVAL_MINUTES):
        send_summary_report(signal_results)
        leaderboard_msg = build_trading_leaderboard(signal_results)
        if leaderboard_msg:
            send_telegram_once(leaderboard_msg)


def main():
    global US_MARKET, TW_MARKET, scanner_health

    if TEST_MODE:
        run_test_mode()
        return

    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit(
            "請設定 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID 環境變數"
        )

    state_path = Path(os.getenv("SCANNER_STATE_PATH", ".scanner-state/state.json"))
    restore_scan_state(state_path)
    scanner_health = {
        "status": "準備中",
        "started_at": now_tw().isoformat(timespec="seconds"),
        "finished_at": None,
        "active_market": None,
        "telegram_ok": None,
        "telegram_sent": 0,
        "telegram_failed": 0,
        "state_saved": False,
        "failure_reason": None,
    }
    # One shared work deadline covers universe loading, dynamic refresh and scan,
    # while leaving time for finally/state cache and the Actions job teardown.
    deadline = time.monotonic() + max(0, MAX_RUN_SECONDS - FINISH_RESERVE_SECONDS)
    try:
        US_MARKET, us_fallback = load_us_market(
            get_us_fallback(), deadline=deadline
        )
        TW_MARKET, tw_fallback = load_tw_market(
            get_tw_fallback(), deadline=deadline
        )
        dynamic_us, dynamic_tw, refreshed, changed = refresh_dynamic_state(
            dynamic_priority_state, US_MARKET, TW_MARKET, deadline=deadline
        )
        if refreshed and changed and (dynamic_us or dynamic_tw):
            send_telegram(format_change_message(dynamic_us, dynamic_tw))
        send_telegram_once("🚀 v16 Institutional Alpha Engine 已啟動")
        send_telegram_once(
            f"股票池載入完成\n美股：{len(US_MARKET)} 檔"
            f"{'（fallback）' if us_fallback else ''}\n台股：{len(TW_MARKET)} 檔"
            f"{'（fallback）' if tw_fallback else ''}"
        )
        if not US_MARKET and not TW_MARKET:
            send_telegram_once("⚠️ 股票池抓取失敗，請檢查資料來源")
        run_scan_once(deadline)
    except Exception as error:
        scanner_health["status"] = "失敗"
        scanner_health["failure_reason"] = f"{type(error).__name__}: {error}"[:300]
        raise
    finally:
        scanner_health["finished_at"] = now_tw().isoformat(timespec="seconds")
        scanner_health["duration_seconds"] = round(
            max(0, time.monotonic() - (deadline - max(0, MAX_RUN_SECONDS - FINISH_RESERVE_SECONDS))), 1
        )
        try:
            scanner_health["state_saved"] = True
            persist_scan_state(state_path)
        except Exception as state_error:
            scanner_health["state_saved"] = False
            scanner_health["state_error"] = f"{type(state_error).__name__}: {state_error}"[:300]
            raise


if __name__ == "__main__":
    main()
