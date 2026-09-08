import requests
import pandas as pd

from main import market_is_open, passes_liquidity_filter

from market_universe import (
    TW_PRIORITY,
    US_PRIORITY,
    advance_cursor,
    dedupe,
    get_tw_market,
    get_us_market,
    make_batch,
    parse_tw_listings,
    parse_us_listings,
)


NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
NVDA|NVIDIA Corporation - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
TEST|Test Common Stock|S|Y|N|100|N|N
BADW|Bad Corp Warrants|S|N|N|100|N|N
BRK.B|Berkshire Class B Common Stock|Q|N|N|100|N|N
File Creation Time: 0907202621:31||||||||
"""

OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
DELL|Dell Technologies Common Stock|N|DELL|N|100|N|DELL
AA.P|Example Preferred Stock|N|AA.P|N|100|N|AA-P
AMX|American Common Stock|A|AMX|N|100|N|AMX
ARCA|Arca Common Stock|P|ARCA|N|100|N|ARCA
"""


class Response:
    def __init__(self, text="", payload=None):
        self.text = text
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses=None, error=None):
        self.responses = iter(responses or [])
        self.error = error

    def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return next(self.responses)


def test_us_parser_filters_exchange_and_non_common_securities():
    assert parse_us_listings(NASDAQ, OTHER) == ["NVDA", "BRK-B", "DELL", "AMX"]


def test_tw_parser_assigns_correct_exchange_suffix_and_filters_invalid_codes():
    rows = [{"公司代號": "2330"}, {"公司代號": "006208"}, {"公司代號": "權證"}]
    assert parse_tw_listings(rows, ".TW") == ["2330.TW"]
    assert parse_tw_listings([{"公司代號": "6488"}], ".TWO") == ["6488.TWO"]


def test_downloaded_universes_include_priority_once():
    us, fallback = get_us_market([], Session([Response(NASDAQ), Response(OTHER)]))
    tw, tw_fallback = get_tw_market([], Session([
        Response(payload=[{"公司代號": "2330"}, {"公司代號": "3711"}]),
        Response(payload=[{"公司代號": "6488"}]),
    ]))

    assert fallback is False and us[:len(US_PRIORITY)] == US_PRIORITY
    assert us.count("NVDA") == 1
    assert tw_fallback is False and tw[:len(TW_PRIORITY)] == TW_PRIORITY
    assert tw.count("2330.TW") == 1
    assert "6488.TWO" in tw


def test_source_failure_uses_existing_pool_without_raising():
    failed = Session(error=requests.ConnectionError("offline"))
    us, us_fallback = get_us_market(["OLD", "NVDA"], failed)
    tw, tw_fallback = get_tw_market(["1101.TW", "2330.TW"], failed)

    assert us_fallback and us == dedupe(US_PRIORITY + ["OLD", "NVDA"])
    assert tw_fallback and tw == dedupe(TW_PRIORITY + ["1101.TW", "2330.TW"])


def test_batch_cursor_wraps_restores_and_deduplicates_priority():
    universe = ["A", "B", "NVDA", "C"]
    first, market_slice = make_batch(universe, 3, 3, ["NVDA", "A", "NVDA"])
    cursor = advance_cursor(universe, 3, market_slice, first)
    second, second_slice = make_batch(universe, cursor, 3, ["NVDA", "A"])
    next_cursor = advance_cursor(universe, cursor, second_slice, second)

    assert market_slice == ["C", "A", "B"]
    assert first == ["NVDA", "A", "C", "B"]
    assert cursor == 2
    assert second == ["NVDA", "A", "C"]
    assert next_cursor == 1


def test_cursor_stops_at_first_unfinished_market_symbol():
    universe = ["A", "B", "P", "C"]
    batch, market_slice = make_batch(universe, 0, 4, ["P"])

    # Priority P and market A completed before timeout. P does not move the
    # cursor independently, and unfinished B must be the next run's first item.
    assert batch == ["P", "A", "B", "C"]
    assert advance_cursor(universe, 0, market_slice, {"P", "A"}) == 1


def test_run_scan_timeout_resumes_at_first_unfinished_market_symbol(monkeypatch):
    import main

    scanned = []
    universe = ["A", "B", "P", "C"]
    ticks = iter([0, 0, 0, 0, 0, 1, 2, 101])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(main, "US_BATCH_SIZE", 4)
    monkeypatch.setattr(main, "US_PRIORITY", ["P"])
    monkeypatch.setattr(main, "us_scan_cursor", 0)
    monkeypatch.setattr(main, "get_active_universe", lambda: (universe, "US"))
    monkeypatch.setattr(main, "market_risk_mode", lambda: False)
    monkeypatch.setattr(main, "market_open_for", lambda ticker: True)
    monkeypatch.setattr(main, "scan_stock", lambda ticker, **kwargs: scanned.append(ticker))
    monkeypatch.setattr(main, "mark_once_interval", lambda *args: False)
    monkeypatch.setattr(main, "send_close_report_if_needed", lambda *args: None)
    monkeypatch.setattr(main, "send_premarket_report_if_needed", lambda *args: None)
    monkeypatch.setattr(main, "send_ai_infra_report_if_needed", lambda: None)
    monkeypatch.setattr(main, "emergency_market_stop_check", lambda *args: None)

    main.run_scan_once(deadline=100)

    assert scanned == ["P", "A"]
    assert main.us_scan_cursor == 1
    _, resumed_slice = make_batch(universe, main.us_scan_cursor, 4, ["P"])
    assert resumed_slice[0] == "B"


def test_market_specific_liquidity_filters():
    us = pd.DataFrame({"Close": [5] * 20, "Volume": [500000] * 20})
    tw = pd.DataFrame({"Close": [10] * 20, "Volume": [100000] * 20})
    assert passes_liquidity_filter("AMD", us)
    assert passes_liquidity_filter("2330.TW", tw)
    assert not passes_liquidity_filter("AMD", tw)


def test_market_hours_use_local_time_and_us_dst():
    assert market_is_open("US", pd.Timestamp("2026-07-06 14:00:00", tz="UTC"))
    assert not market_is_open("US", pd.Timestamp("2026-07-06 13:00:00", tz="UTC"))
    assert market_is_open("US", pd.Timestamp("2026-01-05 15:00:00", tz="UTC"))
    assert market_is_open("TW", pd.Timestamp("2026-07-06 01:30:00", tz="UTC"))
