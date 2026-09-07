"""Durable JSON state for stateless scheduled scanner invocations."""

import json
import os
from pathlib import Path


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"掃描狀態無法讀取，將從空白狀態開始：{error}")
        return {}

    return value if isinstance(value, dict) else {}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)
