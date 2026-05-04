from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trend_harvester.config import get_settings

_WRITE_LOCK = threading.Lock()


def _logs_dir() -> Path:
    root = Path(get_settings().run_logs_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_log_path(run_id: str) -> Path:
    safe_id = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in {"-", "_"})
    return _logs_dir() / f"{safe_id or 'unknown'}.log"


def append_run_log(
    run_id: str,
    message: str,
    *,
    level: str = "INFO",
    event: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts} [{level.upper()}]"
    if event:
        line += f" [{event}]"
    line += f" {str(message).strip()}"
    if payload:
        try:
            compact = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            line += f" {compact}"
        except Exception:
            pass
    with _WRITE_LOCK:
        with run_log_path(run_id).open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")


def read_run_log(run_id: str, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    path = run_log_path(run_id)
    if not path.exists():
        return {"run_id": run_id, "offset": 0, "next_offset": 0, "total_lines": 0, "has_more": False, "lines": []}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = max(0, int(offset))
    if start == 0:
        start = max(0, total - int(limit))
    end = min(total, start + int(limit))
    out = lines[start:end]
    return {
        "run_id": run_id,
        "offset": start,
        "next_offset": end,
        "total_lines": total,
        "has_more": end < total,
        "lines": out,
    }


def delete_run_log(run_id: str) -> None:
    path = run_log_path(run_id)
    with _WRITE_LOCK:
        if path.exists():
            path.unlink(missing_ok=True)
