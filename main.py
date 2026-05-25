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

SIGNAL_SCORE_MIN = 8
SIGNAL_LEADER_MIN = 30
RANKING_SCORE_MIN = 0

TEST_MODE = False

sent_today = set()
signal_state = {}
sent_msg_cache = set()
trade_recommendations = {}

scan_pointer = 0
last_close_report_date = None

TW_CLOSE_REPORT_TIME = 13 * 60 + 45
US_CLOSE_REPORT_TIME = 5 * 60 + 10


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
        url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"

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


def get_tw_market():
    return [
        "2330.TW", "2317.TW", "2382.TW", "6669.TW",
        "3017.TW", "3037.TW", "2308.TW", "3231.TW",
        "2368.TW", "3443.TW",
        "4908.TW", "3450.TW", "4979.TW",
        "2408.TW", "8299.TW",
        "1519.TW", "1503.TW",
        "3324.TW", "3653.TW",
        "2049.TW", "1536.TW",
        "2634.TW", "8222.TW",
    ]


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
    }


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
            and result["leader_score"] >= SIGNAL_LEADER_MIN
        )

        if (
            not force_return
            and result["score"] < RANKING_SCORE_MIN
            and not send_signal
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
# 收盤回測報告
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
            f"題材：{r['theme']}\n"
        )

    return msg


# =========================
# 今日市場分析 / 明日預期
# =========================

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
        "2049.TW", "2634.TW", "8222.TW", "2345.TW"
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
            send_telegram_once(rotation_msg)

        if leaderboard_msg:
            send_telegram_once(leaderboard_msg)

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


send_telegram_once("🚀 v15 Institutional Alpha Engine 已啟動")

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
        today = now_tw().strftime("%Y-%m-%d")

        send_close_report_if_needed("TW")
        send_close_report_if_needed("US")

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
        # Leaderboard / Sector Rotation
        # =========================

        if results:
            rotation_msg = build_sector_rotation(results)
            leaderboard_msg = build_leaderboard(results, top_n=10)

            if rotation_msg:
                send_telegram_once(rotation_msg)

            if leaderboard_msg:
                send_telegram_once(leaderboard_msg)

            if risk_mode:
                send_telegram_once("⚠️ 市場風險模式啟動，所有訊號降級處理")

            signal_results = [
                r for r in results
                if r["send_signal"]
            ]

            send_telegram_once(
                f"🔥 本輪評分 {len(results)} 檔，其中 {len(signal_results)} 檔達正式訊號門檻"
            )

            for r in signal_results[:10]:
                send_it, reason = should_send_signal(r)

                if send_it:
                    record_recommendation(r)

                    upgrade_note = f"\n\n📌 通知原因：{reason}"

                    send_telegram(
                        r["message"] + upgrade_note
                    )

        else:
            print("本輪沒有可排名股票")

        if len(sent_today) > 1000:
            sent_today.clear()

        send_close_report_if_needed("TW")
        send_close_report_if_needed("US")

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        print("主程式錯誤：", e)
        time.sleep(60)