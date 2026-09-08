"""Export the scanner cache into a safe, browser-readable dashboard snapshot."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


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
            "price": row.get("price"),
            "price_source": row.get("price_source", "Yahoo Finance"),
            "price_updated_at": row.get("price_updated_at"),
            "tier": "WATCH",
            "reasons": list(row.get("reasons", []))[:4],
            "catalyst": str(row.get("catalyst", ""))[:180],
            "catalysts": list(row.get("catalysts", []))[:6],
            "headlines": list(row.get("headlines", []))[:5],
            "themes": list(row.get("themes", []))[:5],
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
            "signal_tier": record.get("signal_tier"),
            "signal_action": record.get("signal_action"),
            "position_label": record.get("position_label"),
            "market_regime": record.get("market_regime"),
            "earnings_note": record.get("earnings_note"),
            "conditions": list(record.get("conditions", []))[:8],
            "entry_plan": record.get("entry_plan", {}),
            "price_source": record.get("price_source", "Yahoo Finance"),
            "price_updated_at": record.get("price_updated_at"),
            "catalysts": list(record.get("catalysts", []))[:6],
            "headlines": list(record.get("headlines", []))[:5],
            "outcome": record.get("outcome", {}),
        })
    return output


def _scan_rows(records: object) -> list[dict]:
    if not isinstance(records, list):
        return []
    output = []
    for record in records:
        if not isinstance(record, dict) or not record.get("ticker"):
            continue
        symbol = str(record["ticker"])
        output.append({
            "symbol": symbol,
            "market": "TW" if symbol.endswith((".TW", ".TWO")) else "US",
            "kind": "正式推薦" if record.get("send_signal") else "本輪評分",
            "score": record.get("score", 0),
            "leader_score": record.get("leader_score", 0),
            "price": record.get("price"),
            "tier": record.get("signal_tier") or "WATCH",
            "reasons": list(record.get("conditions", []))[:6],
            "themes": list(record.get("themes", []))[:5],
            "signal_action": record.get("signal_action"),
            "position_pct": record.get("position_pct"),
            "position_label": record.get("position_label"),
            "market_regime": record.get("market_regime"),
            "smart_money_bias": record.get("smart_money_bias"),
            "earnings_note": record.get("earnings_note"),
            "entry_plan": record.get("entry_plan", {}),
            "price_source": record.get("price_source", "Yahoo Finance"),
            "price_updated_at": record.get("price_updated_at"),
            "catalyst": record.get("catalyst", ""),
            "catalysts": list(record.get("catalysts", []))[:6],
            "headlines": list(record.get("headlines", []))[:5],
        })
    return output


def _rotation(candidates: list[dict]) -> list[dict]:
    themes = {}
    for row in candidates:
        row_themes = list(row.get("themes", []))
        if not row_themes:
            row_themes = [reason.replace("板塊強勢", "") for reason in row.get("reasons", [])
                          if isinstance(reason, str) and reason.endswith("板塊強勢")]
        for theme in row_themes:
            bucket = themes.setdefault(theme, {"theme": theme, "score": 0.0, "count": 0, "tickers": [], "relative_strength": 0.0, "strength_samples": 0})
            bucket["score"] += float(row.get("score") or 0)
            bucket["count"] += 1
            if row.get("symbol") not in bucket["tickers"]:
                bucket["tickers"].append(row.get("symbol"))
            strength = row.get("relative_strength_5d")
            if isinstance(strength, (int, float)):
                bucket["relative_strength"] += float(strength)
                bucket["strength_samples"] += 1
    rows = []
    for bucket in themes.values():
        bucket["score"] = round(bucket["score"] / bucket["count"], 1)
        bucket["tickers"] = bucket["tickers"][:5]
        samples = bucket.pop("strength_samples")
        relative = round(bucket.pop("relative_strength") / samples, 2) if samples else 0
        bucket["relative_strength_5d"] = relative
        bucket["temperature"] = "升溫" if relative >= 1 else "降溫" if relative <= -1 else "持平"
        rows.append(bucket)
    return sorted(rows, key=lambda row: (-row["score"], -row["count"], row["theme"]))[:12]


def build_snapshot(state: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    candidates = (
        _recommendation_rows(state.get("trade_recommendations"))
        + _scan_rows(state.get("latest_scan_results"))
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
    unique = []
    seen = set()
    for row in candidates:
        key = (row["symbol"], row["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    recommendations = [
        row for row in _recommendation_rows(state.get("trade_recommendations"))
    ]
    recommendations.sort(key=lambda row: (row.get("date") or "", row["symbol"]), reverse=True)
    health = state.get("scanner_health", {})
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
        "candidate_count": len(unique),
        "candidates": unique[:60],
        "rotation": _rotation(unique),
        "health": health,
        "market_status": health.get("status", "等待掃描"),
        "notifications": list(state.get("notification_history", []))[:30],
        "recommendations": recommendations[:50],
        "notice": "資料來自免費行情與新聞來源，可能延遲；評分僅供研究，不構成投資建議。",
    }


def encrypt_snapshot(snapshot: dict, public_key_path: Path) -> dict:
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    aes_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(
        iv, json.dumps(snapshot, ensure_ascii=False).encode("utf-8"), None
    )
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    encode = lambda value: base64.b64encode(value).decode("ascii")
    return {"version": 1, "encrypted_key": encode(encrypted_key), "iv": encode(iv), "ciphertext": encode(ciphertext)}


def export_dashboard(state_path: Path, output_path: Path, public_key_path: Path | None = None) -> None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    snapshot = build_snapshot(state)
    payload = encrypt_snapshot(snapshot, public_key_path) if public_key_path else snapshot
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path(".scanner-state/state.json"))
    parser.add_argument("--output", type=Path, default=Path("dashboard/data.json"))
    parser.add_argument("--public-key", type=Path)
    args = parser.parse_args()
    export_dashboard(args.state, args.output, args.public_key)


if __name__ == "__main__":
    main()
