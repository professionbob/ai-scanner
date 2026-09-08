"""Walk-forward backtest for the reproducible scanner signal core.

The live scanner also uses current news, option chains and earnings calendars.
Those inputs are not reconstructed here because the free providers do not expose
reliable point-in-time history.  The report labels this limitation explicitly.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import analyze_stock
from main import (
    MAX_CHASE_ABOVE_MA20,
    MIN_VOLUME_RATIO_FOR_SIGNAL,
    SIGNAL_LEADER_MIN,
    SIGNAL_SCORE_MIN,
    analyze_dark_pool_proxy,
    analyze_institutional_flow,
    build_entry_plan,
    build_smart_money_summary,
    classify_setup,
    get_tw_fallback,
    get_us_fallback,
)
from market_universe import TW_PRIORITY, US_PRIORITY


BENCHMARK = {"US": "QQQ", "TW": "0050.TW"}
PRIORITY_TICKERS = US_PRIORITY + TW_PRIORITY
DEFAULT_TICKERS = list(dict.fromkeys(get_us_fallback() + get_tw_fallback()))
LOOKBACK_DAYS = 420
HOLDING_SESSIONS = 60
ROUND_TRIP_COST_PCT = 0.20


@dataclass
class Trade:
    symbol: str
    market: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry: float
    stop: float
    target: float
    exit: float
    return_pct: float
    outcome: str
    holding_sessions: int
    score: float
    leader_score: float
    smart_money_score: float


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(column in frame for column in needed):
        return pd.DataFrame()
    return frame[needed].dropna().sort_index()


def live_core_signal(symbol: str, stock: pd.DataFrame, market: pd.DataFrame) -> dict | None:
    """Replay only inputs that can be known at the historical close."""
    result = analyze_stock(symbol, stock, market, theme="一般", current_position=0)
    if result is None:
        return None

    options = {"options_score": 0, "options_note": "歷史期權資料未納入"}
    dark = analyze_dark_pool_proxy(symbol, stock)
    institution = analyze_institutional_flow(symbol, stock, market)
    smart = build_smart_money_summary(options, dark, institution)
    smart_score = smart["smart_money_score"]
    result["score"] += smart_score
    result["leader_score"] += max(smart_score, 0) * 3
    result["smart_money_score"] = smart_score

    setup, _ = classify_setup(result, stock)
    price = float(stock["Close"].iloc[-1])
    ma20 = float(stock["Close"].rolling(20).mean().iloc[-1])
    ma50 = float(stock["Close"].rolling(50).mean().iloc[-1])
    volume20 = float(stock["Volume"].rolling(20).mean().iloc[-1])
    volume_ratio = float(stock["Volume"].iloc[-1] / volume20) if volume20 else 0
    extended = price > ma20 * MAX_CHASE_ABOVE_MA20

    # The historical free-data test cannot reconstruct earnings-risk or options.
    send = (
        result["score"] >= SIGNAL_SCORE_MIN
        and result["leader_score"] >= SIGNAL_LEADER_MIN
        and smart_score >= 3
        and setup in {"S", "A"}
        and price > ma20
        and price > ma50
        and volume_ratio >= MIN_VOLUME_RATIO_FOR_SIGNAL
        and not extended
        and result["market_regime"] != "RISK_OFF"
    )
    if not send:
        return None
    result["entry_plan"] = build_entry_plan(result, stock)
    return result


def simulate_exit(future: pd.DataFrame, entry: float, stop: float, target: float) -> tuple:
    for sessions, (when, row) in enumerate(future.iloc[:HOLDING_SESSIONS].iterrows(), start=1):
        # Conservative rule when a daily candle crosses both levels.
        if float(row["Low"]) <= stop:
            return when, stop, "STOP", sessions
        if float(row["High"]) >= target:
            return when, target, "TARGET", sessions
    row = future.iloc[min(len(future), HOLDING_SESSIONS) - 1]
    when = future.index[min(len(future), HOLDING_SESSIONS) - 1]
    return when, float(row["Close"]), "TIME", min(len(future), HOLDING_SESSIONS)


def backtest_symbol(symbol: str, frame: pd.DataFrame, benchmark: pd.DataFrame,
                    start: pd.Timestamp, end: pd.Timestamp) -> list[Trade]:
    trades: list[Trade] = []
    next_available = frame.index.min()
    for position in range(220, len(frame) - 1):
        signal_day = frame.index[position]
        if signal_day < start or signal_day > end or signal_day < next_available:
            continue
        history = frame.iloc[: position + 1]
        market = benchmark.loc[:signal_day]
        if len(market) < 220:
            continue
        signal = live_core_signal(symbol, history, market)
        if signal is None:
            continue

        next_bar = frame.iloc[position + 1]
        entry = float(next_bar["Open"])
        planned_stop = float(signal["entry_plan"]["stop_loss"])
        risk = entry - planned_stop
        if risk <= 0:
            continue
        target = entry + risk * 2
        future = frame.iloc[position + 1 :]
        exit_day, exit_price, outcome, held = simulate_exit(future, entry, planned_stop, target)
        net_return = (exit_price / entry - 1) * 100 - ROUND_TRIP_COST_PCT
        market_name = "TW" if symbol.endswith((".TW", ".TWO")) else "US"
        trades.append(Trade(
            symbol=symbol, market=market_name, signal_date=str(signal_day.date()),
            entry_date=str(frame.index[position + 1].date()), exit_date=str(exit_day.date()),
            entry=round(entry, 2), stop=round(planned_stop, 2), target=round(target, 2),
            exit=round(exit_price, 2), return_pct=round(net_return, 2), outcome=outcome,
            holding_sessions=held, score=float(signal["score"]),
            leader_score=float(signal["leader_score"]), smart_money_score=float(signal["smart_money_score"]),
        ))
        next_available = exit_day
    return trades


def summarize(trades: list[Trade], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    returns = [trade.return_pct for trade in trades]
    profitable = [value for value in returns if value > 0]
    targets = [trade for trade in trades if trade.outcome == "TARGET"]
    stops = [trade for trade in trades if trade.outcome == "STOP"]
    return {
        "period": {"start": str(start.date()), "end": str(end.date())},
        "method": "walk_forward_reproducible_core",
        "assumptions": {
            "entry": "signal 後下一交易日開盤價",
            "stop": "訊號日 min(20MA, 20日低點) × 0.97",
            "target": "2R",
            "maximum_holding_sessions": HOLDING_SESSIONS,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "same_day_stop_and_target": "保守假設先觸發停損",
        },
        "limitations": ["未納入歷史新聞輪動", "未納入歷史期權鏈", "未納入歷史財報倒數"],
        "trade_count": len(trades),
        "profitable_win_rate_pct": round(len(profitable) / len(trades) * 100, 2) if trades else None,
        "target_hit_rate_pct": round(len(targets) / len(trades) * 100, 2) if trades else None,
        "stop_rate_pct": round(len(stops) / len(trades) * 100, 2) if trades else None,
        "average_return_pct": round(sum(returns) / len(returns), 2) if trades else None,
        "median_return_pct": round(float(pd.Series(returns).median()), 2) if trades else None,
        "best_trade_pct": round(max(returns), 2) if trades else None,
        "worst_trade_pct": round(min(returns), 2) if trades else None,
        "trades": [asdict(trade) for trade in trades],
    }


def download(tickers: list[str]) -> dict[str, pd.DataFrame]:
    symbols = list(dict.fromkeys(tickers + list(BENCHMARK.values())))
    frames: dict[str, pd.DataFrame] = {}
    # Smaller serial batches avoid yfinance's shared SQLite cookie lock and make
    # partial provider failures visible instead of aborting the whole report.
    for offset in range(0, len(symbols), 40):
        chunk = symbols[offset : offset + 40]
        raw = yf.download(chunk, period="2y", interval="1d", auto_adjust=True,
                          progress=False, threads=False, group_by="ticker", timeout=30)
        level0 = set(map(str, raw.columns.get_level_values(0))) if isinstance(raw.columns, pd.MultiIndex) else set()
        for symbol in chunk:
            if isinstance(raw.columns, pd.MultiIndex) and symbol in level0:
                frames[symbol] = normalize(raw[symbol])
            elif len(chunk) == 1:
                frames[symbol] = normalize(raw)
            else:
                frames[symbol] = pd.DataFrame()
    return frames


def run(tickers: list[str], months: int = 6) -> dict:
    frames = download(tickers)
    latest = max(frame.index.max() for frame in frames.values() if not frame.empty)
    end = pd.Timestamp(latest).tz_localize(None)
    start = end - pd.DateOffset(months=months)
    trades: list[Trade] = []
    for symbol in tickers:
        frame = frames.get(symbol, pd.DataFrame())
        market = "TW" if symbol.endswith((".TW", ".TWO")) else "US"
        benchmark = frames.get(BENCHMARK[market], pd.DataFrame())
        if frame.empty or benchmark.empty:
            continue
        trades.extend(backtest_symbol(symbol, frame, benchmark, start, end))
    trades.sort(key=lambda trade: (trade.signal_date, trade.symbol))
    result = summarize(trades, start, end)
    result["tickers"] = tickers
    result["completed_tickers"] = [symbol for symbol in tickers if not frames.get(symbol, pd.DataFrame()).empty]
    result["missing_tickers"] = [symbol for symbol in tickers if frames.get(symbol, pd.DataFrame()).empty]
    result["universe_note"] = "目前 fallback 股票池快照；不代表歷史當時的完整成分股"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--scope", choices=("fallback", "priority"), default="fallback")
    parser.add_argument("--tickers", nargs="*")
    parser.add_argument("--output", type=Path, default=Path("backtest-results.json"))
    args = parser.parse_args()
    tickers = args.tickers or (PRIORITY_TICKERS if args.scope == "priority" else DEFAULT_TICKERS)
    result = run(tickers, args.months)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "trades"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
