"""Export the scanner cache into a safe, browser-readable dashboard snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def _market_status(market: str, now: datetime) -> dict:
    zone_name = "Asia/Taipei" if market == "TW" else "America/New_York"
    local = now.astimezone(ZoneInfo(zone_name))
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5:
        is_open = False
    elif market == "TW":
        is_open = 9 * 60 <= minute <= 13 * 60 + 30
    else:
        is_open = 9 * 60 + 30 <= minute <= 16 * 60
    return {
        "is_open": is_open,
        "label": "交易中" if is_open else "休市",
        "local_time": local.isoformat(timespec="minutes"),
    }


def _dynamic_rows(rows: object, market: str) -> list[dict]:
    if not isinstance(rows, list):
        return []
    output = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        output.append({
            "symbol": str(row["symbol"]),
            "market": market,
            "kind": "浮動優先",
            "score": row.get("score", 0),
            "price": None,
            "tier": "WATCH",
            "reasons": list(row.get("reasons", []))[:4],
            "catalyst": str(row.get("catalyst", ""))[:180],
            "relative_strength_5d": metrics.get("relative_strength_5d"),
            "volume_ratio": metrics.get("volume_ratio"),
        })
    return output


def _recommendation_rows(records: object) -> list[dict]:
    if not isinstance(records, dict):
        return []
    output = []
    for record in records.values():
        if not isinstance(record, dict) or not record.get("ticker"):
            continue
        symbol = str(record["ticker"])
        output.append({
            "symbol": symbol,
            "market": "TW" if symbol.endswith((".TW", ".TWO")) else "US",
            "kind": "正式推薦",
            "score": record.get("score", 0),
            "leader_score": record.get("leader_score", 0),
            "price": record.get("entry_price"),
            "tier": record.get("setup_grade") or "SIGNAL",
            "reasons": list(record.get("themes", []))[:4],
            "catalyst": record.get("smart_money_bias", ""),
            "position_pct": record.get("position_pct"),
            "date": record.get("date"),
        })
    return output


def build_snapshot(state: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    candidates = (
        _recommendation_rows(state.get("trade_recommendations"))
        + _dynamic_rows(state.get("dynamic_tw_priority"), "TW")
        + _dynamic_rows(state.get("dynamic_us_priority"), "US")
    )
    candidates.sort(
        key=lambda row: (
            0 if row["kind"] == "正式推薦" else 1,
            -float(row.get("score") or 0),
            row["symbol"],
        )
    )
    return {
        "generated_at": now.astimezone(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds"),
        "markets": {
            "TW": _market_status("TW", now),
            "US": _market_status("US", now),
        },
        "last_dynamic_update": state.get("last_dynamic_update"),
        "cursors": {
            "TW": int(state.get("tw_scan_cursor", 0) or 0),
            "US": int(state.get("us_scan_cursor", 0) or 0),
        },
        "candidate_count": len(candidates),
        "candidates": candidates[:40],
        "notice": "資料來自免費行情與新聞來源，可能延遲；評分僅供研究，不構成投資建議。",
    }


def export_dashboard(state_path: Path, output_path: Path) -> None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(build_snapshot(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path(".scanner-state/state.json"))
    parser.add_argument("--output", type=Path, default=Path("dashboard/data.json"))
    args = parser.parse_args()
    export_dashboard(args.state, args.output)


if __name__ == "__main__":
    main()
