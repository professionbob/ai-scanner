import json

import pandas as pd

import dynamic_priority
import main


class FakeClock:
    def __init__(self, current=0):
        self.current = current

    def __call__(self):
        return self.current


def quote_frame(values):
    columns = {}
    for symbol, (price, volume) in values.items():
        columns[(symbol, "Close")] = [price] * 20
        columns[(symbol, "Volume")] = [volume] * 20
    return pd.DataFrame(columns)


def test_slow_news_stops_before_quotes_and_returns_fixed_only():
    clock = FakeClock()
    quote_called = False

    def slow_news(deadline):
        clock.current = deadline + 1
        return ["NVDA"]

    def quotes(*args, **kwargs):
        nonlocal quote_called
        quote_called = True

    us, tw, success = dynamic_priority.update_dynamic_priority(
        1000, budget_seconds=180, clock=clock,
        news_fetcher=slow_news, downloader=quotes,
    )

    assert (us, tw, success) == ([], [], False)
    assert not quote_called
    assert clock.current == 181


def test_quote_candidates_are_capped_and_price_floors_apply():
    clock = FakeClock()
    downloaded = []
    symbols = ["CHEAP", "GOOD", "1234.TW", "5678.TW", "EXTRA"]

    def quotes(requested, **kwargs):
        downloaded.extend(requested)
        return quote_frame({
            "CHEAP": (4.99, 900000),
            "GOOD": (5, 500000),
            "1234.TW": (9.99, 900000),
            "5678.TW": (10, 100000),
        })

    us, tw, success = dynamic_priority.update_dynamic_priority(
        1000, max_quote_candidates=4, clock=clock,
        news_fetcher=lambda deadline: symbols, downloader=quotes,
    )

    assert success
    assert downloaded == symbols[:4]
    assert us == ["GOOD"]
    assert tw == ["5678.TW"]


def test_failed_dynamic_update_still_scans_fixed_then_market_and_saves(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    scanned = []
    observed_deadlines = []
    monkeypatch.setenv("SCANNER_STATE_PATH", str(state_path))
    monkeypatch.setattr(main, "BOT_TOKEN", "token")
    monkeypatch.setattr(main, "CHAT_ID", "chat")
    monkeypatch.setattr(main.time, "monotonic", lambda: 0)
    monkeypatch.setattr(main, "US_BATCH_SIZE", 2)
    monkeypatch.setattr(main, "US_PRIORITY", ["FIXED"])
    def load_us(fallback, deadline):
        observed_deadlines.append(deadline)
        return ["A", "B"], False

    def load_tw(fallback, deadline):
        observed_deadlines.append(deadline)
        return [], True

    def fail_dynamic(deadline, **kwargs):
        observed_deadlines.append(deadline)
        return [], [], False

    monkeypatch.setattr(main, "load_us_market", load_us)
    monkeypatch.setattr(main, "load_tw_market", load_tw)
    monkeypatch.setattr(main, "update_dynamic_priority", fail_dynamic)
    monkeypatch.setattr(main, "market_is_open", lambda market, moment=None: market == "US")
    monkeypatch.setattr(main, "market_open_for", lambda ticker: True)
    monkeypatch.setattr(main, "market_risk_mode", lambda: False)
    monkeypatch.setattr(main, "scan_stock", lambda ticker, **kwargs: scanned.append(ticker))
    monkeypatch.setattr(main, "send_telegram", lambda *args: None)
    monkeypatch.setattr(main, "send_telegram_once", lambda *args: None)
    monkeypatch.setattr(main, "mark_once_interval", lambda *args: False)
    monkeypatch.setattr(main, "send_close_report_if_needed", lambda *args: None)
    monkeypatch.setattr(main, "send_premarket_report_if_needed", lambda *args: None)
    monkeypatch.setattr(main, "send_ai_infra_report_if_needed", lambda: None)
    monkeypatch.setattr(main, "emergency_market_stop_check", lambda *args: None)

    main.main()

    saved = json.loads(state_path.read_text())
    assert scanned == ["FIXED", "A", "B"]
    assert observed_deadlines == [630, 630, 630]
    assert saved["us_scan_cursor"] == 0
    assert "us_dynamic_priority" in saved
