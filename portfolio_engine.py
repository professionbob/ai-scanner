last_portfolio_state = {}
import yfinance as yf
from trades import TRADES

THEME_MAP = {
    "AI基建": ["NVDA","AMD","AVGO","MRVL","TSM","ARM","APLD","NBIS","CRWV","DELL","SMCI","ORCL","ANET","VRT","ONDS"],
    "光通訊": ["AAOI","LITE","COHR","FN","CIEN","NOK","AXTI"],
    "HBM / 記憶體": ["MU","WDC","STX","SNDK"],
    "電力 / 核電": ["VRT","ETN","PWR","GEV","CEG","SMR","CCJ","BWXT"],
    "國防 / 無人機": ["ONDS","PLTR","KTOS","AVAV","LMT","NOC","RTX","GD","TXT","RKLB"],
    "機器人 / 自動化": ["TSLA","TER","SYM","ROK","ISRG","ABBNY","FANUY"],
    "資安": ["PANW","CRWD","ZS","FTNT","NET","OKTA"],
    "AI軟體": ["PLTR","SNOW","NOW","DDOG","MDB","AI","CRM"],
    "太空 / 衛星": ["RKLB","ASTS","IRDM","PL","LUNR"],
}

def themes_of(ticker):
    themes = []
    for theme, tickers in THEME_MAP.items():
        if ticker in tickers:
            themes.append(theme)
    return themes if themes else ["一般市場股"]

def calculate_positions():
    positions = {}

    for t in TRADES:
        ticker = t["ticker"]
        action = t["action"].upper()
        shares = t["shares"]
        price = t["price"]

        if ticker not in positions:
            positions[ticker] = {
                "shares": 0,
                "cost": 0.0,
                "realized_pnl": 0.0
            }

        pos = positions[ticker]

        if action == "BUY":
            pos["cost"] += shares * price
            pos["shares"] += shares

        elif action == "SELL":
            if pos["shares"] <= 0:
                continue

            avg_cost = pos["cost"] / pos["shares"]
            sell_shares = min(shares, pos["shares"])

            pos["realized_pnl"] += (price - avg_cost) * sell_shares
            pos["cost"] -= avg_cost * sell_shares
            pos["shares"] -= sell_shares

    clean_positions = {}

    for ticker, pos in positions.items():
        if pos["shares"] > 0:
            clean_positions[ticker] = {
                "avg_cost": pos["cost"] / pos["shares"],
                "shares": pos["shares"],
                "realized_pnl": pos["realized_pnl"],
                "themes": themes_of(ticker)
            }

    return clean_positions

def get_price(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="1d", auto_adjust=True, progress=False)
        if df.empty:
            return None
        return float(df["Close"].squeeze().iloc[-1])
    except Exception:
        return None

def portfolio_snapshot():
    positions = calculate_positions()

    total_value = 0
    total_cost = 0
    unrealized_pnl = 0
    theme_exposure = {}
    rows = []

    for ticker, pos in positions.items():
        price = get_price(ticker)
        if price is None:
            continue

        value = price * pos["shares"]
        cost = pos["avg_cost"] * pos["shares"]
        pnl = value - cost
        pnl_pct = pnl / cost * 100 if cost > 0 else 0

        total_value += value
        total_cost += cost
        unrealized_pnl += pnl

        for theme in pos["themes"]:
            theme_exposure[theme] = theme_exposure.get(theme, 0) + value

        rows.append({
            "ticker": ticker,
            "shares": pos["shares"],
            "avg_cost": pos["avg_cost"],
            "price": price,
            "value": value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "themes": pos["themes"]
        })

    for theme in theme_exposure:
        theme_exposure[theme] = theme_exposure[theme] / total_value * 100 if total_value > 0 else 0

    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl / total_cost * 100 if total_cost > 0 else 0,
        "theme_exposure": theme_exposure,
        "positions": rows
    }

def market_regime():
    try:
        qqq = yf.download("QQQ", period="6mo", interval="1d", auto_adjust=True, progress=False)
        soxx = yf.download("SOXX", period="6mo", interval="1d", auto_adjust=True, progress=False)
        vix = yf.download("^VIX", period="1mo", interval="1d", auto_adjust=True, progress=False)

        q = qqq["Close"].squeeze()
        s = soxx["Close"].squeeze()
        v = float(vix["Close"].squeeze().iloc[-1])

        q_up = q.iloc[-1] > q.rolling(20).mean().iloc[-1]
        s_up = s.iloc[-1] > s.rolling(20).mean().iloc[-1]

        if q_up and s_up and v < 20:
            return "🟢 Risk-On", "可正常執行 A/B 級訊號"
        elif not q_up or v > 25:
            return "🔴 Risk-Off", "降低倉位，不追高，只保留最強主線"
        else:
            return "🟡 Neutral", "小倉試單，等主線確認"

    except Exception:
        return "⚪ Unknown", "資料不足"

def portfolio_risk_report():
    snap = portfolio_snapshot()
    global last_portfolio_state
    regime, regime_note = market_regime()

    warnings = []

    for theme, pct in snap["theme_exposure"].items():
        if pct > 50:
            warnings.append(f"⚠️ {theme} 曝險過高：{round(pct, 1)}%")

    for p in snap["positions"]:
        position_pct = p["value"] / snap["total_value"] * 100 if snap["total_value"] > 0 else 0
        if position_pct > 35:
            warnings.append(f"⚠️ {p['ticker']} 單股曝險過高：{round(position_pct, 1)}%")

    msg = f"""
📊 Portfolio Intelligence

市場狀態：
{regime}
{regime_note}

總市值：
{round(snap["total_value"], 2)}

未實現損益：
{round(snap["unrealized_pnl"], 2)}
{round(snap["unrealized_pnl_pct"], 2)}%

Theme 曝險：
"""

    for theme, pct in sorted(snap["theme_exposure"].items(), key=lambda x: x[1], reverse=True):
        msg += f"{theme}: {round(pct, 1)}%\n"

    if warnings:
        msg += "\n風險提醒：\n"
        for w in warnings:
            msg += w + "\n"
    current_state = {
    "regime": regime,
    "warnings": tuple(sorted(warnings))
}

previous_state = last_portfolio_state.get("portfolio")

# 沒變化就不通知
if previous_state == current_state:
    return None

last_portfolio_state["portfolio"] = current_state
return msg