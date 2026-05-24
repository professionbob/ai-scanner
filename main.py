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

BOT_TOKEN = "8846284007:AAEZz4f50N8g1JcC6P8Z2ujcA2hx32-gv5A"
CHAT_ID = "8851496243"


# =========================
# Config
# =========================

SCAN_INTERVAL = 300
MAX_SCAN_PER_ROUND = 300

# 正式訊號門檻
SIGNAL_SCORE_MIN = 8
SIGNAL_LEADER_MIN = 30

# 排名最低門檻，測試時建議 0，正式可改成 5 或 8
RANKING_SCORE_MIN = 0

# 測試模式
TEST_MODE = False

sent_today = set()
scan_pointer = 0


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

    if is_tw(ticker):
        if n.weekday() >= 5:
            return False

        return 9 * 60 <= minutes <= 13 * 60 + 30

    # 美股，台灣時間
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
# 台股股票池
# =========================

def get_tw_market():

    tw_tickers = [

        # AI / PCB / CPO
        "2330.TW",
        "2317.TW",
        "2382.TW",
        "6669.TW",
        "3017.TW",
        "3037.TW",
        "2308.TW",
        "3231.TW",
        "2368.TW",
        "3443.TW",

        # 光通訊
        "4908.TW",
        "3450.TW",
        "4979.TW",

        # 記憶體
        "2408.TW",
        "8299.TW",

        # 電力 / 機電
        "1519.TW",
        "1503.TW",

        # 散熱
        "3324.TW",
        "3653.TW",

        # 機器人 / 自動化
        "2049.TW",
        "1536.TW",

        # 軍工
        "2634.TW",
        "8222.TW",
    ]

    return tw_tickers
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

        if risk_mode:
            result["score"] -= 2
            result["conditions"].append("外部市場風險模式啟動")

        send_signal = (
            result["score"] >= SIGNAL_SCORE_MIN
            and
            result["leader_score"] >= SIGNAL_LEADER_MIN
        )

        # 排名門檻
        if (
            not force_return
            and
            result["score"] < RANKING_SCORE_MIN
            and
            not send_signal
        ):
            return None

        msg = format_telegram_message(result)

        return {
            "ticker": ticker,
            "score": result["score"],
            "leader_score": result["leader_score"],
            "themes": themes,
            "message": msg,
            "send_signal": send_signal,
            "price": result.get("price"),
            "setup_grade": result.get("setup_grade"),
            "market_regime": result.get("market_regime"),
        }

    except Exception as e:
        print(f"{ticker} 掃描錯誤：", e)
        return None


# =========================
# 測試選股
# =========================

def run_test_mode():
    test_tickers = [
        "NVDA", "AVGO", "PLTR", "CRWV", "NBIS",
        "AAOI", "LITE", "MU", "SMCI", "CLS",
        "AMD", "SOFI", "TSLA", "ARM", "MRVL"
    ]

    send_telegram("🧪 測試選股模式啟動")

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

        if rotation_msg:
            send_telegram(rotation_msg)

        if leaderboard_msg:
            send_telegram(leaderboard_msg)

        signal_results = [
            r for r in test_results
            if r["send_signal"]
        ]

        if signal_results:
            send_telegram(
                f"🔥 測試中共有 {len(signal_results)} 檔達正式訊號門檻"
            )

            for r in signal_results[:10]:
                send_telegram(r["message"])
        else:
            send_telegram(
                "📌 測試結果：目前沒有股票達正式訊號門檻，但已產生評分與排名"
            )

    else:
        send_telegram("⚠️ 測試結果：沒有任何股票可評分")

    send_telegram("🧪 測試選股模式結束")


# =========================
# 測試模式入口
# =========================

if TEST_MODE:
    run_test_mode()
    exit()


# =========================
# 啟動
# =========================

send_telegram("🚀 v15 Institutional Alpha Engine 已啟動")


# =========================
# 主程式
# =========================

market_universe = (
    get_us_market()
    +
    get_tw_market()
)()

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
                risk_mode=risk_mode,
                force_return=False
            )

            if result:
                results.append(result)

                if result["send_signal"]:
                    sent_today.add(key)

        results = sorted(
            results,
            key=lambda x: x["leader_score"],
            reverse=True
        )

        # =========================
        # Leaderboard / Sector Rotation
        # =========================

        if results:
            rotation_msg = build_sector_rotation(results)
            leaderboard_msg = build_leaderboard(results, top_n=10)

            if rotation_msg:
                send_telegram(rotation_msg)

            if leaderboard_msg:
                send_telegram(leaderboard_msg)

            if risk_mode:
                send_telegram("⚠️ 市場風險模式啟動，所有訊號降級處理")

            signal_results = [
                r for r in results
                if r["send_signal"]
            ]

            send_telegram(
                f"🔥 本輪評分 {len(results)} 檔，其中 {len(signal_results)} 檔達正式訊號門檻"
            )

            for r in signal_results[:10]:
                send_telegram(r["message"])

        else:
            print("本輪沒有可排名股票")

        if len(sent_today) > 1000:
            sent_today.clear()

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print("主程式錯誤：", e)
        time.sleep(60)