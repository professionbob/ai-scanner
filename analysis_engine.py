# =========================
# 股票選股 / 進出場 最終整合版
# =========================

import numpy as np
import pandas as pd


# =========================
# 技術指標
# =========================

def add_indicators(df):
    df = df.copy()

    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA150"] = df["Close"].rolling(150).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    df["VOL20"] = df["Volume"].rolling(20).mean()
    df["Volume_Ratio"] = df["Volume"] / df["VOL20"]

    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()

    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean()

    df["High_20"] = df["High"].rolling(20).max()
    df["Low_20"] = df["Low"].rolling(20).min()
    df["High_50"] = df["High"].rolling(50).max()
    df["Low_50"] = df["Low"].rolling(50).min()

    return df


# =========================
# 市場 Regime
# =========================

def detect_market_regime(market_df):
    m = market_df.iloc[-1]

    if m["Close"] > m["MA20"] > m["MA50"]:
        return "RISK_ON"
    elif m["Close"] < m["MA20"] < m["MA50"]:
        return "RISK_OFF"
    elif m["Close"] > m["MA20"] and m["MA20"] < m["MA50"]:
        return "RECOVERY"
    else:
        return "NEUTRAL"


# =========================
# K線 / 型態辨識
# =========================

def detect_patterns(df):
    recent = df.tail(60)
    last = df.iloc[-1]

    patterns = []

    box_high = recent["High"].rolling(20).max().iloc[-2]
    box_low = recent["Low"].rolling(20).min().iloc[-2]

    if last["Close"] > box_high and last["Volume_Ratio"] >= 1.3:
        patterns.append("箱型突破")

    if recent["Low"].idxmin() < recent.index[-10]:
        cup_depth = (recent["High"].max() - recent["Low"].min()) / recent["High"].max()
        handle_pullback = (recent["High"].tail(10).max() - recent["Low"].tail(10).min()) / recent["High"].tail(10).max()
        if 0.12 <= cup_depth <= 0.40 and handle_pullback <= 0.15 and last["Close"] > recent["High"].tail(10).max() * 0.98:
            patterns.append("杯柄型態")

    low_1 = recent["Low"].iloc[:30].min()
    low_2 = recent["Low"].iloc[30:].min()
    if abs(low_1 - low_2) / low_1 <= 0.06 and last["Close"] > recent["Close"].mean():
        patterns.append("雙底")

    volatility_contracting = (
        recent["ATR"].tail(10).mean() <
        recent["ATR"].iloc[-30:-10].mean()
    )

    if volatility_contracting and last["Close"] > last["MA20"]:
        patterns.append("VCP 波動收斂")

    higher_lows = recent["Low"].tail(20).iloc[-1] > recent["Low"].tail(20).iloc[0]
    lower_highs = recent["High"].tail(20).iloc[-1] < recent["High"].tail(20).iloc[0]

    if higher_lows and lower_highs:
        patterns.append("三角收斂")

    if last["Close"] > last["MA20"] and last["MA20"] > last["MA50"]:
        patterns.append("多頭排列")

    return patterns


# =========================
# 假突破過濾
# =========================

def false_breakout_filter(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    breakout_level = df["High"].rolling(20).max().iloc[-2]

    if last["Close"] > breakout_level:
        if last["Volume_Ratio"] < 1.2:
            return False, "突破量不足"
        if last["Close"] < last["Open"]:
            return False, "突破收黑K"
        if last["Close"] < breakout_level * 1.01:
            return False, "突破幅度不足"

    return True, "通過假突破過濾"


# =========================
# 題材熱度
# =========================

def get_theme_score(theme):
    theme_scores = {
        "AI": 90,
        "AI基建": 95,
        "光通訊": 94,
        "HBM": 92,
        "記憶體": 90,
        "先進封裝": 88,
        "核能": 85,
        "電力": 83,
        "機器人": 82,
        "國防": 80,
        "SaaS": 72,
        "Fintech": 70,
        "一般": 60,
    }

    return theme_scores.get(theme, 60)


# =========================
# RR / 停損停利
# =========================

def calculate_trade_plan(price, atr, breakout_level, ma20):
    stop = round(min(ma20, price - atr * 1.5), 2)

    risk = price - stop

    tp1 = round(price + risk * 2, 2)
    tp2 = round(price + risk * 3, 2)
    tp3 = round(price + risk * 5, 2)

    rr = round((tp1 - price) / (price - stop), 2) if price > stop else 0

    aggressive_low = round(price * 0.995, 2)
    aggressive_high = round(price * 1.002, 2)

    pullback_low = round(min(breakout_level, ma20), 2)
    pullback_high = round(max(breakout_level, ma20), 2)

    return {
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "aggressive_entry": f"{aggressive_low} ~ {aggressive_high}",
        "pullback_entry": f"{pullback_low} ~ {pullback_high}",
    }


# =========================
# 加倉建議
# =========================

def position_sizing(setup_grade, market_regime, current_position):
    base = {
        "A+": 0.30,
        "A": 0.20,
        "B": 0.10,
        "C": 0.05,
        "NO_TRADE": 0.00,
    }.get(setup_grade, 0.00)

    if market_regime == "RISK_OFF":
        base *= 0.4
    elif market_regime == "NEUTRAL":
        base *= 0.7
    elif market_regime == "RECOVERY":
        base *= 0.85

    add_shares = int(current_position * base)

    return {
        "suggested_add_pct_of_current": round(base * 100, 1),
        "suggested_add_shares": add_shares,
    }


# =========================
# 勝率評級
# =========================

def win_rate_grade(score):
    if score >= 12:
        return "高勝率 A+"
    elif score >= 10:
        return "偏高勝率 A"
    elif score >= 8:
        return "普通 B"
    elif score >= 6:
        return "觀察 C"
    else:
        return "不建議"


# =========================
# 主分析引擎
# =========================

def analyze_stock(
    symbol,
    df,
    market_df,
    benchmark_df=None,
    theme="一般",
    current_position=0,
):
    df = add_indicators(df).dropna()
    market_df = add_indicators(market_df).dropna()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = round(last["Close"], 2)
    breakout_level = df["High"].rolling(20).max().iloc[-2]

    market_regime = detect_market_regime(market_df)
    patterns = detect_patterns(df)
    fake_ok, fake_reason = false_breakout_filter(df)
    theme_score = get_theme_score(theme)

    score = 0
    conditions = []

    if price > last["MA20"]:
        score += 1
        conditions.append("站上20MA")

    if price > last["MA50"]:
        score += 1
        conditions.append("站上50MA")

    if last["MA20"] > prev["MA20"]:
        score += 1
        conditions.append("20MA走升")

    if last["MA20"] > last["MA50"]:
        score += 1
        conditions.append("20MA > 50MA")

    if last["Volume_Ratio"] >= 1.5:
        score += 2
        conditions.append(f"放量 {last['Volume_Ratio']:.2f}x")
    elif last["Volume_Ratio"] >= 1.2:
        score += 1
        conditions.append(f"溫和放量 {last['Volume_Ratio']:.2f}x")

    if 50 <= last["RSI"] <= 75:
        score += 1
        conditions.append(f"RSI 健康：{last['RSI']:.2f}")
    elif last["RSI"] > 75:
        conditions.append(f"RSI 過熱：{last['RSI']:.2f}")

    if last["MACD"] > last["MACD_SIGNAL"]:
        score += 1
        conditions.append("MACD偏多")

    if price > breakout_level:
        score += 2
        conditions.append("突破20日高點")

    if fake_ok:
        score += 1
        conditions.append(fake_reason)
    else:
        score -= 2
        conditions.append(fake_reason)

    if theme_score >= 85:
        score += 2
        conditions.append(f"題材熱度高：{theme_score}/100")
    elif theme_score >= 70:
        score += 1
        conditions.append(f"題材熱度中上：{theme_score}/100")

    if market_regime == "RISK_ON":
        score += 2
        conditions.append("市場 Risk-On")
    elif market_regime == "RECOVERY":
        score += 1
        conditions.append("市場 Recovery")
    elif market_regime == "RISK_OFF":
        score -= 3
        conditions.append("市場 Risk-Off，降低追價")

    for p in patterns:
        score += 1
        conditions.append(p)

    trade_plan = calculate_trade_plan(
        price=price,
        atr=last["ATR"],
        breakout_level=breakout_level,
        ma20=last["MA20"],
    )

    if score >= 12 and market_regime != "RISK_OFF":
        setup_grade = "A+"
        action = "可以小量追價，但仍需嚴守停損"
        order_valid = "當日有效，若隔日未延續放量則取消"
    elif score >= 10:
        setup_grade = "A"
        action = "可分批建倉，優先等回測不破"
        order_valid = "1~2個交易日有效"
    elif score >= 8:
        setup_grade = "B"
        action = "適合觀察或等回測，不建議重倉追價"
        order_valid = "等待回測價有效"
    elif score >= 6:
        setup_grade = "C"
        action = "只觀察，不主動進場"
        order_valid = "無"
    else:
        setup_grade = "NO_TRADE"
        action = "禁止追價"
        order_valid = "無"

    sizing = position_sizing(setup_grade, market_regime, current_position)

    result = {
        "symbol": symbol,
        "price": price,
        "theme": theme,
        "theme_score": theme_score,
        "score": score,
        "setup_grade": setup_grade,
        "win_rate_grade": win_rate_grade(score),
        "market_regime": market_regime,
        "patterns": patterns,
        "conditions": conditions,
        "action": action,
        "order_valid": order_valid,
        "trade_plan": trade_plan,
        "position_sizing": sizing,
    }

    return result


# =========================
# Telegram 訊息格式
# =========================

def format_telegram_message(result):
    tp = result["trade_plan"]
    ps = result["position_sizing"]

    patterns_text = "、".join(result["patterns"]) if result["patterns"] else "無明顯型態"
    conditions_text = "\n".join([f"✅ {c}" for c in result["conditions"]])

    msg = f"""
🔥 {result['setup_grade']} 技術訊號

股票：{result['symbol']}
題材：{result['theme']}
價格：{result['price']}

分數：{result['score']}
勝率評級：{result['win_rate_grade']}
市場狀態：{result['market_regime']}
題材熱度：{result['theme_score']}/100

型態：
{patterns_text}

條件：
{conditions_text}

進場策略：
{result['action']}

追價區間：
{tp['aggressive_entry']}

回測區間：
{tp['pullback_entry']}

停損：
{tp['stop']}

停利：
TP1：{tp['tp1']}
TP2：{tp['tp2']}
TP3：{tp['tp3']}

RR Ratio：
{tp['rr']}

建議加倉：
原持有股數的 {ps['suggested_add_pct_of_current']}%
約 {ps['suggested_add_shares']} 股

掛單有效時間：
{result['order_valid']}

⚠️ 紀律：
跌破停損不凹單；若突破後跌回箱體，視為假突破。
"""
    return msg.strip()