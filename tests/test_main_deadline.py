import pytest

import main


def test_detect_themes_accepts_ticker_and_business_summary():
    themes = main.detect_themes(
        "NVDA",
        "GPU data center infrastructure for AI server and inference workloads",
    )

    assert "AI基建" in themes


def _quiet_main(monkeypatch):
    monkeypatch.setattr(main, "BOT_TOKEN", "test")
    monkeypatch.setattr(main, "CHAT_ID", "test")
    monkeypatch.setattr(main, "restore_scan_state", lambda path: None)
    monkeypatch.setattr(main, "send_telegram", lambda *args: None)
    monkeypatch.setattr(main, "send_telegram_once", lambda *args: None)
    monkeypatch.setattr(main, "get_us_fallback", lambda: [])
    monkeypatch.setattr(main, "get_tw_fallback", lambda: [])


def test_universes_dynamic_update_and_scan_share_reserved_deadline(monkeypatch):
    _quiet_main(monkeypatch)
    deadlines = []
    monkeypatch.setattr(main, "MAX_RUN_SECONDS", 720)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100)
    monkeypatch.setattr(main, "load_us_market", lambda fallback, deadline: (deadlines.append(("US", deadline)) or (["NVDA"], False)))
    monkeypatch.setattr(main, "load_tw_market", lambda fallback, deadline: (deadlines.append(("TW", deadline)) or (["2330.TW"], False)))
    monkeypatch.setattr(main, "refresh_dynamic_state", lambda *args, deadline: (deadlines.append(("dynamic", deadline)) or ([], [], False, False)))
    monkeypatch.setattr(main, "run_scan_once", lambda deadline: deadlines.append(("scan", deadline)))
    monkeypatch.setattr(main, "persist_scan_state", lambda path: None)

    main.main()

    assert deadlines == [(name, 730) for name in ("US", "TW", "dynamic", "scan")]


def test_slow_universe_failure_still_persists_state_in_finally(monkeypatch):
    _quiet_main(monkeypatch)
    saved = []
    monkeypatch.setattr(main.time, "monotonic", lambda: 0)
    monkeypatch.setattr(main, "load_us_market", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("slow")))
    monkeypatch.setattr(main, "persist_scan_state", lambda path: saved.append(path))

    with pytest.raises(TimeoutError, match="slow"):
        main.main()

    assert len(saved) == 1
