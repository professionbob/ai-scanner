import yfinance as yf
from ta.volatility import AverageTrueRange
from ta.momentum import RSIIndicator
from ta.trend import MACD
from positions import POSITIONS

def manage_positions():
    messages = []

    for ticker, pos in POSITIONS.items():
        try:
            avg_cost = pos["avg_cost"]
            shares = pos["shares"]
            style = pos.get("style", "swing")

            df = yf.download(
                ticker,
                period="6mo",
                interval="1d",
                auto_adjust=True,
                progress=False
            )

            if df.empty or len(df) < 60:
                continue

            close = df["Close"].squeeze()
            high = df["High"].squeeze()
            low = df["Low"].squeeze()
            volume = df["Volume"].squeeze()

            price = float(close.iloc[-1])

            ma5 = close.rolling(5).mean()
            ma10 = close.rolling(10).mean()
            ma20 = close.rolling(20).mean()
            ma50 = close.rolling(50).mean()

            atr = AverageTrueRange(
                high, low, close, window=14
            ).average_true_range()

            atr_value = float(atr.iloc[-1])

            rsi = RSIIndicator(close).rsi()
            rsi_value = float(rsi.iloc[-1])

            macd_obj = MACD(close)
            macd = macd_obj.macd()
            macd_signal = macd_obj.macd_signal()

            gain_pct = (price / avg_cost - 1) * 100

            # 動態停損
            if style == "trend":
                trailing_stop = max(
                    avg_cost * 0.93,
                    price - atr_value * 2.5,
                    ma20.iloc[-1] * 0.97
                )
            else:
                trailing_stop = max(
                    avg_cost * 0.93,
                    price - atr_value * 2,
                    ma10.iloc[-1] * 0.97
                )

            # 動態停利
            tp1 = avg_cost * 1.08
            tp2 = avg_cost * 1.15
            tp3 = avg_cost * 1.25

            # 趨勢強時上修停利
            trend_strong = (
                price > ma20.iloc[-1]
                and price > ma50.iloc[-1]
                and macd.iloc[-1] > macd_signal.iloc[-1]
                and rsi_value < 75
            )

            if trend_strong:
                tp3 = max(tp3, price + atr_value * 3)

            risk_note = "正常持有"

            if price < ma20.iloc[-1]:
                risk_note = "⚠️ 跌破20MA，注意趨勢轉弱"

            if rsi_value > 75:
                risk_note = "⚠️ RSI過熱，可考慮部分停利"

            if price <= trailing_stop:
                risk_note = "🚨 觸及動態停損區，應評估出場"

            msg = f"""
📌 持倉更新

股票：{ticker}
股數：{shares}
成本：{round(avg_cost, 2)}
現價：{round(price, 2)}
損益：{round(gain_pct, 2)}%

動態停損：
{round(trailing_stop, 2)}

動態停利：
TP1：{round(tp1, 2)}
TP2：{round(tp2, 2)}
TP3：{round(tp3, 2)}

均線：
5MA：{round(float(ma5.iloc[-1]), 2)}
10MA：{round(float(ma10.iloc[-1]), 2)}
20MA：{round(float(ma20.iloc[-1]), 2)}
50MA：{round(float(ma50.iloc[-1]), 2)}

RSI：{round(rsi_value, 2)}
狀態：{risk_note}
"""
            messages.append(msg)

        except Exception as e:
            print(ticker, e)

    return messages