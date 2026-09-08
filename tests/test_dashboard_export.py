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


def test_snapshot_exports_scan_health_details_and_rotation():
    snapshot = build_snapshot({
        "scanner_health": {"status": "完成", "telegram_ok": True, "state_saved": True},
        "notification_history": [{"status": "成功", "summary": "TW 分批掃描啟動"}],
        "latest_scan_results": [{
            "ticker": "2330.TW", "price": 1200, "score": 12,
            "leader_score": 50, "themes": ["AI基建"], "conditions": ["站上20MA"],
            "send_signal": True, "signal_tier": "A", "position_pct": 7,
            "entry_plan": {"stop_loss": 1100, "rr_ratio": 2},
        }],
    })
    assert snapshot["health"]["telegram_ok"] is True
    assert snapshot["notifications"][0]["status"] == "成功"
    assert snapshot["candidates"][0]["entry_plan"]["stop_loss"] == 1100
    assert snapshot["rotation"][0]["theme"] == "AI基建"


def test_snapshot_exports_prices_targets_news_outcomes_and_failure_reason():
    snapshot = build_snapshot({
        "scanner_health": {"status": "失敗", "failure_reason": "TimeoutError: quote"},
        "trade_recommendations": {"x": {
            "date": "2026-09-08", "ticker": "NVDA", "entry_price": 100,
            "price_updated_at": "2026-09-08T15:59:00-04:00",
            "price_source": "Yahoo Finance",
            "entry_plan": {"stop_loss": 92, "target_1": 108, "target_2": 116},
            "headlines": [{"title": "New order", "url": "https://example.com"}],
            "outcome": {"status": "第一目標達標", "highest_gain_pct": 9},
        }},
    })
    row = snapshot["recommendations"][0]
    assert snapshot["health"]["failure_reason"].startswith("TimeoutError")
    assert row["entry_plan"]["target_2"] == 116
    assert row["headlines"][0]["title"] == "New order"
    assert row["outcome"]["highest_gain_pct"] == 9
