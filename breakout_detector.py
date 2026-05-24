def detect_breakout(df):

    latest = df.iloc[-1]

    recent_high = (
        df["High"]
        .rolling(20)
        .max()
        .iloc[-2]
    )

    volume_confirm = (
        latest["Volume_Ratio"] > 1.5
    )

    breakout = (
        latest["Close"] > recent_high
        and volume_confirm
    )

    return breakout