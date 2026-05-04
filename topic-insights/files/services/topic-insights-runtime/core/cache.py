from __future__ import annotations
import json
import hashlib
import sqlite3
import time
from pathlib import Path
from core.config import settings

_DB_PATH = Path(settings.data_dir) / "cache.db"

def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.execute(
        "CREATE TABLE IF NOT EXISTS api_cache (key TEXT PRIMARY KEY, value_json TEXT, created_at INTEGER, ttl_seconds INTEGER)"
    )
    return c

def cache_get(key: str) -> dict | None:
    now = int(time.time())
    with _conn() as c:
        row = c.execute("SELECT value_json, created_at, ttl_seconds FROM api_cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        value_json, created_at, ttl = row
        if ttl is not None and created_at + ttl < now:
            c.execute("DELETE FROM api_cache WHERE key=?", (key,))
            return None
        return json.loads(value_json)

def cache_set(key: str, value: dict, ttl_seconds: int) -> None:
    now = int(time.time())
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO api_cache (key, value_json, created_at, ttl_seconds) VALUES (?,?,?,?)",
            (key, json.dumps(value), now, ttl_seconds),
        )

def make_cache_key(prefix: str, parts: dict) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"
