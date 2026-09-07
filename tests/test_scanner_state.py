import json
from datetime import datetime

import main
from scanner_state import load_state, save_state


def test_state_round_trip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    state = {"scan_pointer": 42, "sent_today": ["2026-09-07-US"]}

    save_state(path, state)

    assert load_state(path) == state
    assert not path.with_suffix(".json.tmp").exists()


def test_invalid_state_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")

    assert load_state(path) == {}


def test_main_state_preserves_cursor_and_throttles(tmp_path):
    path = tmp_path / "state.json"
    main.sent_today = {"2026-09-07-US-summary-1"}
    main.signal_state = {"NVDA": {"score": 12}}
    main.sent_msg_cache = {"message"}
    main.trade_recommendations = {"NVDA": {"price": 100}}
    main.us_scan_cursor = 100
    main.tw_scan_cursor = 25
    main.last_close_report_date = "2026-09-07-US"
    main.last_premarket_report_date = "2026-09-07-TW"
    main.last_ai_infra_report_date = "2026-09-07"
    main.last_emergency_alert_time = datetime(2026, 9, 7, 1, 2, 3)

    main.persist_scan_state(path)
    main.us_scan_cursor = 0
    main.tw_scan_cursor = 0
    main.sent_today = set()
    main.restore_scan_state(path)

    assert main.us_scan_cursor == 100
    assert main.tw_scan_cursor == 25
    assert main.sent_today == {"2026-09-07-US-summary-1"}
    assert main.last_emergency_alert_time == datetime(2026, 9, 7, 1, 2, 3)
    assert json.loads(path.read_text(encoding="utf-8"))["signal_state"]["NVDA"]["score"] == 12


def test_v1_scan_pointer_is_restored_as_us_cursor(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"scan_pointer": 17})

    main.restore_scan_state(path)

    assert main.us_scan_cursor == 17
    assert main.tw_scan_cursor == 0
