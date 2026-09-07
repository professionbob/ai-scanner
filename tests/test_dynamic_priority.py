from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dynamic_priority import (
    build_dynamic_priorities,
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
