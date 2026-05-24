import pandas as pd
import numpy as np


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
    df["VOL60"] = df["Volume"].rolling(60).mean()
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

    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()
    df["ATR_PCT"] = df["ATR"] / df["Close"]

    df["High_20"] = df["High"].rolling(20).max()
    df["Low_20"] = df["Low"].rolling(20).min()

    df["High_52W"] = df["High"].rolling(252).max()
    df["Low_52W"] = df["Low"].rolling(252).min()

    return df


# =========================
# 市場 Regime
# =========================

def detect_market_regime(market_df):
    m = market_df.iloc[-1]

    if m["Close"] > m["MA20"] > m["MA50"]:
        return "RISK_ON"

    if m["Close"] < m["MA20"] < m["MA50"]:
        return "RISK_OFF"

    if m["Close"] > m["MA20"] and m["MA20"] < m["MA50"]:
        return "RECOVERY"

    return "NEUTRAL"


# =========================
# Weekly Trend
# =========================

def detect_weekly_trend(df):
    weekly = df.resample("W").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    if len(weekly) < 40:
        return "INSUFFICIENT", 0

    weekly["WMA10"] = weekly["Close"].rolling(10).mean()
    weekly["WMA30"] = weekly["Close"].rolling(30).mean()

    last = weekly.iloc[-1]
    prev = weekly.iloc[-2]

    score = 0

    if last["Close"] > last["WMA10"]:
        score += 1

    if last["Close"] > last["WMA30"]:
        score += 1

    if last["WMA10"] > last["WMA30"]:
        score += 1

    if last["WMA10"] > prev["WMA10"]:
        score += 1

    if score >= 4:
        return "WEEKLY_UPTREND_STRONG", 3

    if score >= 3:
        return "WEEKLY_UPTREND", 2

    if score >= 2:
        return "WEEKLY_NEUTRAL", 0

    return "WEEKLY_WEAK", -2


# =========================
# 52週高點距離
# =========================

def detect_52w_proximity(df):
    last = df.iloc[-1]

    high_52w = last["High_52W"]

    if pd.isna(high_52w) or high_52w <= 0:
        return "INSUFFICIENT", 0, None

    distance = (last["Close"] / high_52w) - 1

    if distance >= -0.03:
        return "距離52週高點 3% 內", 3, distance

    if distance >= -0.08:
        return "距離52週高點 8% 內", 2, distance

    if distance >= -0.15:
        return "距離52週高點 15% 內", 1, distance

    return "遠離52週高點", -1, distance


# =========================
# 成交量異常偵測
# =========================

def detect_volume_anomaly(df):
    if len(df) < 80:
        return "INSUFFICIENT", 0

    last_volume = df["Volume"].iloc[-1]
    vol_60 = df["Volume"].iloc[-60:]

    percentile_95 = vol_60.quantile(0.95)
    percentile_90 = vol_60.quantile(0.90)

    if last_volume >= percentile_95:
        return "成交量大於近60日95分位", 3

    if last_volume >= percentile_90:
        return "成交量大於近60日90分位", 2

    if df["Volume_Ratio"].iloc[-1] >= 1.5:
        return "成交量高於20日均量1.5倍", 1

    return "成交量無異常", 0


# =========================
# Earnings Gap Engine
# =========================

def detect_earnings_gap(df):
    if len(df) < 30:
        return "INSUFFICIENT", 0

    last = df.iloc[-1]
    prev = df.iloc[-2]

    gap_pct = (last["Open"] / prev["Close"]) - 1
    close_strength = (last["Close"] / last["Open"]) - 1
    volume_ratio = last["Volume_Ratio"]

    if gap_pct >= 0.08 and close_strength >= 0 and volume_ratio >= 2:
        return "Earnings Gap Up 強勢延續", 4

    if gap_pct >= 0.05 and volume_ratio >= 1.5:
        return "Gap Up 放量", 3

    if gap_pct <= -0.08 and volume_ratio >= 2:
        return "重大 Gap Down 風險", -4

    return "無明顯 Earnings Gap", 0


# =========================
# 型態辨識
# =========================

def detect_patterns(df):
    recent = df.tail(80)
    last = df.iloc[-1]

    patterns = []
    score = 0

    if len(recent) < 80:
        return patterns, score

    price = last["Close"]

    box_high = recent["High"].tail(20).max()
    box_low = recent["Low"].tail(20).min()

    if price > box_high * 0.99 and last["Volume_Ratio"] >= 1.3:
        patterns.append("箱型突破")
        score += 2

    high_60 = recent["Close"].tail(60).max()
    low_60 = recent["Close"].tail(60).min()
    left_high = recent["Close"].iloc[-60:-40].max()
    right_high = recent["Close"].iloc[-20:].max()
    handle_low = recent["Close"].iloc[-10:].min()

    cup_depth = (high_60 - low_60) / high_60
    handle_depth = (right_high - handle_low) / right_high

    if (
        0.12 <= cup_depth <= 0.40
        and right_high >= left_high * 0.90
        and handle_depth <= 0.15
        and price >= right_high * 0.97
    ):
        patterns.append("杯柄型態")
        score += 3

    atr_short = recent["ATR"].tail(10).mean()
    atr_mid = recent["ATR"].iloc[-30:-10].mean()
    atr_long = recent["ATR"].iloc[-60:-30].mean()

    vol_short = recent["Volume"].tail(10).mean()
    vol_mid = recent["Volume"].iloc[-30:-10].mean()

    if (
        atr_short < atr_mid
        and atr_mid < atr_long
        and vol_short < vol_mid
        and price >= recent["Close"].tail(20).max() * 0.97
    ):
        patterns.append("VCP 波動收斂")
        score += 3

    impulse = (recent["Close"].iloc[-15] / recent["Close"].iloc[-30]) - 1
    flag_pullback = (
        recent["Close"].tail(15).max()
        - recent["Close"].tail(15).min()
    ) / recent["Close"].tail(15).max()

    if (
        impulse >= 0.18
        and flag_pullback <= 0.12
        and price >= recent["Close"].tail(15).max() * 0.98
        and last["Volume_Ratio"] >= 1.2
    ):
        patterns.append("Bull Flag")
        score += 2

    base_range = (
        recent["Close"].tail(40).max()
        - recent["Close"].tail(40).min()
    ) / recent["Close"].tail(40).max()

    if (
        base_range <= 0.18
        and price >= recent["Close"].tail(40).max() * 0.97
        and last["Volume_Ratio"] >= 1.2
    ):
        patterns.append("Flat Base")
        score += 2

    left_shoulder = recent["Close"].iloc[-60:-45].min()
    head = recent["Close"].iloc[-45:-25].min()
    right_shoulder = recent["Close"].iloc[-25:-10].min()
    neckline = recent["Close"].iloc[-25:].max()

    if (
        head < left_shoulder
        and head < right_shoulder
        and right_shoulder >= head * 1.05
        and price >= neckline * 0.98
    ):
        patterns.append("頭肩底")
        score += 2

    low_1 = recent["Low"].iloc[-60:-30].min()
    low_2 = recent["Low"].iloc[-30:].min()

    if (
        abs(low_1 - low_2) / low_1 <= 0.06
        and price > recent["Close"].mean()
    ):
        patterns.append("雙底")
        score += 2

    if price > last["MA20"] > last["MA50"]:
        patterns.append("多頭排列")
        score += 1

    return patterns, score


# =========================
# 假突破過濾
# =========================

def false_breakout_filter(df):
    last = df.iloc[-1]
    breakout_level = df["High"].rolling(20).max().iloc[-2]

    if last["Close"] > breakout_level:
        if last["Volume_Ratio"] < 1.2:
            return False, "突破量不足"

        if last["Close"] < last["Open"]:
            return False, "突破收黑K"

        if last["Close"] < breakout_level * 1.005:
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
        "HBM / 記憶體": 90,
        "先進封裝": 88,
        "核能": 85,
        "電力": 83,
        "電力 / 核電": 83,
        "機器人": 82,
        "機器人 / 自動化": 82,
        "國防": 80,
        "國防 / 無人機": 80,
        "資安": 78,
        "太空": 76,
        "太空 / 衛星": 76,
        "AI生技": 74,
        "AI生技 / 醫療科技": 74,
        "SaaS": 72,
        "Fintech": 70,
        "一般": 60,
        "一般市場股": 60,
    }

    return theme_scores.get(theme, 60)


# =========================
# Leader Score
# =========================

def calculate_leader_score(
    price,
    rsi,
    volume_ratio,
    relative_strength_ok,
    weekly_score,
    proximity_score,
    pattern_score,
    earnings_gap_score,
    theme_score
):
    leader_score = 0

    if relative_strength_ok:
        leader_score += 20

    if price > 0:
        leader_score += max(proximity_score, 0) * 8

    if 55 <= rsi <= 75:
        leader_score += 15
    elif 75 < rsi <= 82:
        leader_score += 8

    if volume_ratio >= 2:
        leader_score += 15
    elif volume_ratio >= 1.5:
        leader_score += 10
    elif volume_ratio >= 1.2:
        leader_score += 5

    leader_score += max(weekly_score, 0) * 8
    leader_score += max(pattern_score, 0) * 5
    leader_score += max(earnings_gap_score, 0) * 5

    if theme_score >= 85:
        leader_score += 15
    elif theme_score >= 75:
        leader_score += 8

    return min(round(leader_score, 1), 100)


# =========================
# RR / 停損停利
# =========================

def calculate_trade_plan(price, atr, breakout_level, ma20):
    stop = round(min(ma20, price - atr * 1.5), 2)

    risk = price - stop

    if risk <= 0:
        risk = price * 0.05
        stop = round(price - risk, 2)

    tp1 = round(price + risk * 2, 2)
    tp2 = round(price + risk * 3, 2)
    tp3 = round(price + risk * 5, 2)

    rr = round((tp1 - price) / (price - stop), 2)

    aggressive_low = round(price * 0.995, 2)
    aggressive_high = round(price * 1.002, 2)

    pullback_low = round(min(breakout_level, ma20), 2)
    pullback_high = round(max(breakout_level, ma20), 2)

    conservative_low = round(stop * 1.02, 2)
    conservative_high = round(stop * 1.05, 2)

    return {
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "aggressive_entry": f"{aggressive_low} ~ {aggressive_high}",
        "pullback_entry": f"{pullback_low} ~ {pullback_high}",
        "conservative_entry": f"{conservative_low} ~ {conservative_high}",
    }


# =========================
# 倉位建議
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

    if current_position <= 0:
        add_shares = 0
    else:
        add_shares = int(current_position * base)

    return {
        "suggested_add_pct_of_current": round(base * 100, 1),
        "suggested_add_shares": add_shares,
    }


# =========================
# 勝率評級
# =========================

def win_rate_grade(score, leader_score):
    combined = score + leader_score * 0.2

    if combined >= 18:
        return "A+｜高勝率主升段"
    if combined >= 15:
        return "A｜偏高勝率"
    if combined >= 12:
        return "B｜可觀察"
    if combined >= 9:
        return "C｜早期轉強"
    return "D｜不建議"


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

    if len(df) < 80 or len(market_df) < 80:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = round(float(last["Close"]), 2)
    breakout_level = round(float(df["High"].rolling(20).max().iloc[-2]), 2)

    market_regime = detect_market_regime(market_df)

    weekly_trend, weekly_score = detect_weekly_trend(df)
    proximity_text, proximity_score, distance_52w = detect_52w_proximity(df)
    volume_text, volume_anomaly_score = detect_volume_anomaly(df)
    earnings_gap_text, earnings_gap_score = detect_earnings_gap(df)

    patterns, pattern_score = detect_patterns(df)

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

    if price > last["MA150"] and price > last["MA200"]:
        score += 1
        conditions.append("站上150MA與200MA")

    if last["MA150"] > last["MA200"]:
        score += 1
        conditions.append("150MA > 200MA")

    if last["Volume_Ratio"] >= 2:
        score += 2
        conditions.append(f"強放量 {last['Volume_Ratio']:.2f}x")
    elif last["Volume_Ratio"] >= 1.5:
        score += 1
        conditions.append(f"放量 {last['Volume_Ratio']:.2f}x")

    if 50 <= last["RSI"] <= 75:
        score += 1
        conditions.append(f"RSI 健康：{last['RSI']:.2f}")
    elif 75 < last["RSI"] <= 82:
        conditions.append(f"RSI 偏熱但可接受：{last['RSI']:.2f}")
    elif last["RSI"] > 82:
        score -= 1
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

    if weekly_score > 0:
        score += weekly_score
        conditions.append(f"週線趨勢：{weekly_trend}")
    elif weekly_score < 0:
        score += weekly_score
        conditions.append(f"週線偏弱：{weekly_trend}")

    score += proximity_score
    conditions.append(proximity_text)

    score += volume_anomaly_score
    conditions.append(volume_text)

    score += earnings_gap_score
    conditions.append(earnings_gap_text)

    score += pattern_score

    for p in patterns:
        conditions.append(p)

    # Relative Strength vs benchmark
    try:
        stock_20d = df["Close"].iloc[-1] / df["Close"].iloc[-20] - 1
        market_20d = market_df["Close"].iloc[-1] / market_df["Close"].iloc[-20] - 1
        relative_strength_ok = stock_20d > market_20d

        if relative_strength_ok:
            score += 2
            conditions.append("Relative Strength 強於市場")
        else:
            conditions.append("Relative Strength 弱於市場")

    except Exception:
        relative_strength_ok = False

    leader_score = calculate_leader_score(
        price=price,
        rsi=float(last["RSI"]),
        volume_ratio=float(last["Volume_Ratio"]),
        relative_strength_ok=relative_strength_ok,
        weekly_score=weekly_score,
        proximity_score=proximity_score,
        pattern_score=pattern_score,
        earnings_gap_score=earnings_gap_score,
        theme_score=theme_score
    )

    trade_plan = calculate_trade_plan(
        price=price,
        atr=float(last["ATR"]),
        breakout_level=breakout_level,
        ma20=float(last["MA20"])
    )

    if score >= 18 and market_regime != "RISK_OFF":
        setup_grade = "A+"
        action = "可以小量追價，但必須嚴守停損"
        order_valid = "當日有效，若隔日未延續放量則取消"

    elif score >= 15:
        setup_grade = "A"
        action = "可分批建倉，優先等回測不破"
        order_valid = "1~2個交易日有效"

    elif score >= 12:
        setup_grade = "B"
        action = "適合觀察或等回測，不建議重倉追價"
        order_valid = "等待回測價有效"

    elif score >= 9:
        setup_grade = "C"
        action = "早期轉強，只觀察或極小倉試單"
        order_valid = "無"

    else:
        setup_grade = "NO_TRADE"
        action = "禁止追價"
        order_valid = "無"

    # 額外追價限制
    distance_from_ma20 = price / last["MA20"] - 1

    if distance_from_ma20 > 0.10:
        action = "適合等回測"
        conditions.append("距離20MA超過10%，追價風險偏高")

    if last["RSI"] > 82:
        action = "禁止追價"
        conditions.append("RSI過熱，禁止追價")

    if trade_plan["rr"] < 1.5:
        action = "禁止追價"
        conditions.append("RR Ratio 不足 1.5")

    sizing = position_sizing(setup_grade, market_regime, current_position)

    result = {
        "symbol": symbol,
        "price": price,
        "theme": theme,
        "theme_score": theme_score,
        "score": score,
        "leader_score": leader_score,
        "setup_grade": setup_grade,
        "win_rate_grade": win_rate_grade(score, leader_score),
        "market_regime": market_regime,
        "weekly_trend": weekly_trend,
        "patterns": patterns if patterns else ["無明顯型態"],
        "conditions": conditions,
        "action": action,
        "order_valid": order_valid,
        "trade_plan": trade_plan,
        "position_sizing": sizing,
        "distance_52w": distance_52w,
        "volume_anomaly": volume_text,
        "earnings_gap": earnings_gap_text,
    }

    return result


# =========================
# Telegram 訊息格式
# =========================

def format_telegram_message(result):
    tp = result["trade_plan"]
    ps = result["position_sizing"]

    patterns_text = "、".join(result["patterns"])
    conditions_text = "\n".join([f"✅ {c}" for c in result["conditions"]])

    if result["distance_52w"] is None:
        distance_text = "資料不足"
    else:
        distance_text = f"{round(result['distance_52w'] * 100, 2)}%"

    msg = f"""
🔥 {result['setup_grade']} 技術訊號

股票：{result['symbol']}
題材：{result['theme']}
價格：{result['price']}

總分：{result['score']}
Leader Score：{result['leader_score']}/100
勝率評級：{result['win_rate_grade']}

市場狀態：{result['market_regime']}
週線趨勢：{result['weekly_trend']}
題材熱度：{result['theme_score']}/100

52週高點距離：
{distance_text}

成交量異常：
{result['volume_anomaly']}

Earnings Gap：
{result['earnings_gap']}

型態：
{patterns_text}

條件：
{conditions_text}

━━━━━━━━━━

🧠 自動交易判斷

操作建議：
{result['action']}

掛單有效時間：
{result['order_valid']}

追價區間：
{tp['aggressive_entry']}

回測區間：
{tp['pullback_entry']}

保守低接區：
{tp['conservative_entry']}

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

⚠️ 紀律：
跌破停損不凹單；突破後跌回箱體，視為假突破。
"""
    return msg.strip()