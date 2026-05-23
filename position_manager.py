import yfinance as yf
from ta.volatility import AverageTrueRange
from ta.momentum import RSIIndicator
from ta.trend import MACD
from portfolio_engine import calculate_positions

last_position_state = {}

def manage_positions():
    messages = []
    positions = calculate_positions()

    for ticker, pos in positions.items():
        try:
            avg_cost = pos["avg_cost"]
            shares = pos["shares"]
            style = "trend"
            max_add_times = 2
            add_times = 0

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
            vol20 = volume.rolling(20).mean()

            atr = AverageTrueRange(high, low, close, window=14).average_true_range()
            atr_value = float(atr.iloc[-1])
            atr_pct = atr_value / price

            rsi = RSIIndicator(close).rsi()
            rsi_value = float(rsi.iloc[-1])

            macd_obj = MACD(close)
            macd = macd_obj.macd()
            macd_signal = macd_obj.macd_signal()

            volume_ratio = float(volume.iloc[-1] / vol20.iloc[-1])
            gain_pct = (price / avg_cost - 1) * 100

            trend_strong = (
                price > ma20.iloc[-1]
                and price > ma50.iloc[-1]
                and ma20.iloc[-1] > ma20.iloc[-5]
                and macd.iloc[-1] > macd_signal.iloc[-1]
                and 55 <= rsi_value <= 72
            )

            super_trend = (
                trend_strong
                and price > ma5.iloc[-1]
                and volume_ratio >= 1.3
                and gain_pct > 5
            )

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

            # Break-even stop
            breakeven_stop = None
            if gain_pct >= 8:
                breakeven_stop = avg_cost
                trailing_stop = max(trailing_stop, breakeven_stop)

            # 動態停利
            tp1 = avg_cost * 1.08
            tp2 = avg_cost * 1.15
            tp3 = avg_cost * 1.25

            if trend_strong:
                tp3 = max(tp3, price + atr_value * 3)

            if super_trend:
                tp3 = max(tp3, price + atr_value * 4)

            # 金字塔加倉邏輯
            add_position_pct = 0
            add_position_shares = 0
            add_position_note = "不建議加倉"

            if add_times >= max_add_times:
                add_position_note = "已達設定最大加倉次數，不建議再加倉"

            elif super_trend and gain_pct >= 5 and gain_pct < 15:
                add_position_pct = 0.20
                add_position_note = "🚀 趨勢超強，可評估加倉原持股 20%"

            elif trend_strong and gain_pct >= 8 and gain_pct < 20:
                add_position_pct = 0.10
                add_position_note = "🔥 趨勢強勢，可評估加倉原持股 10%"

            elif gain_pct >= 20:
                add_position_note = "⚠️ 已有較大漲幅，不建議追倉，改用移動停損保護獲利"

            add_position_shares = int(shares * add_position_pct)

            # 部分止盈
            partial_profit_note = "暫不需要部分止盈"

            if price >= tp1 and price < tp2:
                partial_profit_note = "可考慮先停利 20%～30%"

            elif price >= tp2 and price < tp3:
                partial_profit_note = "可考慮停利 30%～50%，剩餘抱趨勢"

            elif price >= tp3:
                partial_profit_note = "已接近高階目標，可考慮分批大幅收割"

            # 風險狀態
            if price <= trailing_stop:
                status = "🚨 觸及動態停損區，應評估出場"

            elif price < ma20.iloc[-1]:
                status = "⚠️ 跌破20MA，注意趨勢轉弱"

            elif rsi_value > 75:
                status = "⚠️ RSI過熱，可考慮部分停利"

            elif super_trend:
                status = "🚀 趨勢超強，可評估小量追倉"

            elif trend_strong:
                status = "🔥 趨勢強勢，續抱觀察"

            else:
                status = "正常持有"

            current_state = {
                "price": round(price, 2),
                "trailing_stop": round(float(trailing_stop), 2),
                "tp1": round(float(tp1), 2),
                "tp2": round(float(tp2), 2),
                "tp3": round(float(tp3), 2),
                "status": status,
                "rsi": round(float(rsi_value), 2),
                "add_shares": add_position_shares,
                "partial_profit_note": partial_profit_note
            }

            previous_state = last_position_state.get(ticker)

            should_notify = False
            notify_reason = []

            if previous_state is None:
                should_notify = True
                notify_reason.append("首次持倉更新")

            else:
                if current_state["status"] != previous_state["status"]:
                    should_notify = True
                    notify_reason.append("狀態改變")

                if current_state["add_shares"] != previous_state["add_shares"]:
                    should_notify = True
                    notify_reason.append("加倉建議改變")

                if current_state["partial_profit_note"] != previous_state["partial_profit_note"]:
                    should_notify = True
                    notify_reason.append("止盈建議改變")

                stop_change = abs(
                    current_state["trailing_stop"]
                    - previous_state["trailing_stop"]
                )

                if stop_change >= max(price * 0.01, 0.10):
                    should_notify = True
                    notify_reason.append("動態停損明顯變動")

            last_position_state[ticker] = current_state

            if not should_notify:
                continue

            msg = f"""
📌 持倉更新

通知原因：
{", ".join(notify_reason)}

股票：{ticker}
股數：{shares}
成本：{round(avg_cost, 2)}
現價：{round(price, 2)}
損益：{round(gain_pct, 2)}%

動態停損：
{current_state["trailing_stop"]}

Break-even Stop：
{round(breakeven_stop, 2) if breakeven_stop else "尚未啟動"}

動態停利：
TP1：{current_state["tp1"]}
TP2：{current_state["tp2"]}
TP3：{current_state["tp3"]}

加倉建議：
{add_position_note}
建議加倉股數：{add_position_shares} 股
目前加倉次數：{add_times}/{max_add_times}

部分止盈：
{partial_profit_note}

均線：
5MA：{round(float(ma5.iloc[-1]), 2)}
10MA：{round(float(ma10.iloc[-1]), 2)}
20MA：{round(float(ma20.iloc[-1]), 2)}
50MA：{round(float(ma50.iloc[-1]), 2)}

Volume Ratio：{round(volume_ratio, 2)}x
ATR%：{round(atr_pct * 100, 2)}%
RSI：{current_state["rsi"]}

狀態：
{status}
"""
            messages.append(msg)

        except Exception as e:
            print(ticker, e)

    return messages