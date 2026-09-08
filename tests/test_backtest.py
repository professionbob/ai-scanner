import pandas as pd

from backtest import simulate_exit, summarize, Trade


def bars(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="B"))


def test_same_day_stop_and_target_is_conservative():
    future = bars([{"Open": 100, "High": 112, "Low": 94, "Close": 108}])
    _, price, outcome, _ = simulate_exit(future, 100, 95, 110)
    assert (price, outcome) == (95, "STOP")


def test_target_exit():
    future = bars([
        {"Open": 100, "High": 104, "Low": 98, "Close": 102},
        {"Open": 103, "High": 111, "Low": 101, "Close": 109},
    ])
    _, price, outcome, held = simulate_exit(future, 100, 95, 110)
    assert (price, outcome, held) == (110, "TARGET", 2)


def test_summary_reports_both_win_definitions():
    sample = [
        Trade("AAA", "US", "2026-01-01", "2026-01-02", "2026-01-10", 100, 95, 110, 110, 9.8, "TARGET", 6, 10, 40, 3),
        Trade("BBB", "US", "2026-01-01", "2026-01-02", "2026-01-10", 100, 95, 110, 98, -2.2, "TIME", 6, 10, 40, 3),
    ]
    result = summarize(sample, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-30"))
    assert result["profitable_win_rate_pct"] == 50
    assert result["target_hit_rate_pct"] == 50
