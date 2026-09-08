from datetime import datetime, timezone

from dashboard_export import build_snapshot


def test_snapshot_combines_recommendations_and_dynamic_priorities():
    state = {
        "tw_scan_cursor": 30,
        "us_scan_cursor": 20,
        "last_dynamic_update": "2026-09-08T01:00:00+00:00",
        "trade_recommendations": {
            "2026-09-08-NVDA": {
                "date": "2026-09-08",
                "ticker": "NVDA",
                "entry_price": 150.5,
                "score": 14,
                "leader_score": 51,
                "themes": ["AI基建"],
                "setup_grade": "S",
                "smart_money_bias": "偏多",
            }
        },
        "dynamic_tw_priority": [{
            "symbol": "2330.TW",
            "score": 82,
            "reasons": ["半導體板塊強勢", "5日相對強度 +3.2%"],
            "catalyst": "營收優於預期",
            "metrics": {"relative_strength_5d": 3.2, "volume_ratio": 1.6},
        }],
    }
    snapshot = build_snapshot(
        state, datetime(2026, 9, 8, 1, 30, tzinfo=timezone.utc)
    )
    assert snapshot["candidate_count"] == 2
    assert snapshot["candidates"][0]["symbol"] == "NVDA"
    assert snapshot["candidates"][1]["symbol"] == "2330.TW"
    assert snapshot["markets"]["TW"]["is_open"] is True
    assert snapshot["cursors"] == {"TW": 30, "US": 20}


def test_snapshot_tolerates_empty_or_malformed_state():
    snapshot = build_snapshot({"dynamic_us_priority": "bad"})
    assert snapshot["candidate_count"] == 0
    assert snapshot["candidates"] == []
