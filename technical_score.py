import pandas as pd


def calculate_technical_score(df):

    score = 0

    latest = df.iloc[-1]

    # =========================
    # MA Trend
    # =========================

    if latest["Close"] > latest["MA20"]:
        score += 2

    if latest["Close"] > latest["MA50"]:
        score += 2

    if latest["MA20"] > latest["MA50"]:
        score += 2

    # =========================
    # Volume
    # =========================

    if latest["Volume_Ratio"] > 1.5:
        score += 2

    # =========================
    # RSI
    # =========================

    if 55 < latest["RSI"] < 75:
        score += 2

    # =========================
    # MACD
    # =========================

    if latest["MACD"] > latest["MACD_Signal"]:
        score += 2

    return score