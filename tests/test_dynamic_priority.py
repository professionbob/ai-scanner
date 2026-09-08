from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dynamic_priority import (
    DynamicDeadlineExceeded,
    build_dynamic_priorities,
    fetch_news,
    momentum_score,
    parse_news_items,
    refresh_dynamic_state,
)


NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def prices(growth=0.15, volume=1_000_000):
    close = [100 * (1 + growth * i / 29) for i in range(30)]
    volumes = [volume] * 29 + [volume * 2]
    return pd.DataFrame({"Close": close, "Volume": volumes})


def article(symbol, title="Company wins major AI contract", hours=2):
    return {"title": title, "link": f"https://example.test/{symbol}",
            "providerPublishTime": int((NOW - timedelta(hours=hours)).timestamp()),
            "relatedTickers": [symbol]}


def loader(symbol):
    if symbol in ("SPY", "^TWII"):
        return prices(0.02, 2_000_000)
    return prices()


def test_news_uses_explicit_related_ticker_and_age_not_company_name():
    items = [article("NVDA"), article("FAKE", "NVIDIA wins order"), article("AMD", hours=80)]
    parsed = parse_news_items(items, {"NVDA", "AMD"}, NOW)
    assert [x["symbol"] for x in parsed] == ["NVDA"]
    assert parsed[0]["catalysts"] == ["訂單"]


def test_momentum_and_rotation_scoring_uses_rs_volume_and_trend():
    score, metrics = momentum_score(prices(0.20), prices(0.01))
    assert score > 25
    assert metrics["relative_strength_5d"] > 0
    assert metrics["relative_strength_20d"] > 0
    assert metrics["volume_ratio"] > 1
    assert metrics["trend_vs_ma20"] > 0

    news = [article("NVDA", "AI semiconductor earnings beat"),
            article("AMD", "AI semiconductor revenue guidance")]
    us, tw = build_dynamic_priorities(["NVDA", "AMD"], [], news, loader, NOW)
    assert not tw and {row["symbol"] for row in us} == {"NVDA", "AMD"}
    assert any("板塊強勢" in reason for reason in us[0]["reasons"])


def test_limits_and_low_liquidity_filter():
    news = [article(f"S{i}") for i in range(20)] + [article("2330.TW")]

    def mixed(symbol):
        return prices(volume=10 if symbol == "S0" else 1_000_000)

    us, tw = build_dynamic_priorities([f"S{i}" for i in range(20)], ["2330.TW"], news, mixed, NOW)
    assert len(us) == 15 and all(row["symbol"] != "S0" for row in us)
    assert [row["symbol"] for row in tw] == ["2330.TW"]


def test_price_floor_filters_us_and_taiwan_candidates():
    news = [article("CHEAP"), article("1234.TW")]

    def cheap(symbol):
        frame = prices(volume=1_000_000)
        if symbol == "CHEAP":
            frame["Close"] = 4.99
        elif symbol == "1234.TW":
            frame["Close"] = 9.99
        return frame

    us, tw = build_dynamic_priorities(["CHEAP"], ["1234.TW"], news, cheap, NOW)
    assert us == [] and tw == []


def test_news_requests_use_remaining_deadline_as_external_timeout():
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"news": []}

    class Session:
        def __init__(self):
            self.timeouts = []

        def get(self, *args, **kwargs):
            self.timeouts.append(kwargs["timeout"])
            return Response()

    session = Session()
    fetch_news(session, deadline=110, clock=lambda: 100)
    assert session.timeouts and all(timeout == 10 for timeout in session.timeouts)


def test_expired_deadline_skips_all_external_calls_and_falls_back():
    calls = []
    state = {}

    def news_loader(**kwargs):
        calls.append("news")
        return [article("NVDA")]

    us, tw, refreshed, _ = refresh_dynamic_state(
        state, ["NVDA"], [], NOW, news_loader, loader,
        deadline=99, clock=lambda: 100,
    )
    assert us == tw == []
    assert refreshed and calls == []


def test_price_loader_receives_bounded_timeout_and_deadline_interrupts_work():
    timeouts = []
    ticks = iter([0, 0, 20])

    def timed_loader(symbol, timeout):
        timeouts.append((symbol, timeout))
        return prices()

    with pytest.raises(DynamicDeadlineExceeded):
        build_dynamic_priorities(
            ["NVDA"], [], [article("NVDA")], timed_loader, NOW,
            deadline=10, clock=lambda: next(ticks),
        )
    assert timeouts == [("SPY", 10), ("^TWII", 10)]


def test_sixty_minute_cache_does_not_call_sources():
    state = {"last_dynamic_update": (NOW - timedelta(minutes=59)).isoformat(),
             "dynamic_us_priority": [{"symbol": "NVDA"}], "dynamic_tw_priority": []}

    def forbidden():
        raise AssertionError("cache should be used")

    us, tw, refreshed, changed = refresh_dynamic_state(state, [], [], NOW, forbidden, loader)
    assert [x["symbol"] for x in us] == ["NVDA"]
    assert not refreshed and not changed and not tw


def test_source_failure_falls_back_atomically_and_is_cached():
    state = {"dynamic_us_priority": [{"symbol": "OLD"}], "dynamic_tw_priority": []}

    def offline():
        raise RuntimeError("offline")

    us, tw, refreshed, changed = refresh_dynamic_state(state, ["NVDA"], [], NOW, offline, loader)
    assert us == tw == []
    assert refreshed and changed
    assert state["dynamic_us_priority"] == []
    assert state["last_dynamic_update"] == NOW.isoformat()


@pytest.mark.parametrize("broken", [None, "bad date", 42])
def test_corrupt_or_expired_cache_rebuilds_safely(broken):
    state = {"last_dynamic_update": broken, "dynamic_us_priority": "broken",
             "dynamic_tw_priority": None}
    us, tw, refreshed, _ = refresh_dynamic_state(
        state, ["NVDA"], [], NOW, lambda: [article("NVDA")], loader
    )
    assert refreshed and [row["symbol"] for row in us] == ["NVDA"] and tw == []
