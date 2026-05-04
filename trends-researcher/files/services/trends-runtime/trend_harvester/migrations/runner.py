from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trend_harvester.config import get_settings


def _db_path_from_url(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)
    if database_url.startswith("sqlite:////"):
        return database_url.replace("sqlite:////", "/", 1)
    raise ValueError("Only sqlite URLs are supported by migration runner")


def run_migrations() -> None:
    settings = get_settings()
    db_path = _db_path_from_url(settings.database_url)
    sql_dir = Path(__file__).resolve().parent / "sql"
    scripts = sorted(sql_dir.glob("*.sql"))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        existing = {row[0] for row in conn.execute("SELECT version FROM schema_version")}

        for script in scripts:
            version = int(script.name.split("_", 1)[0])
            if version in existing:
                continue
            sql = script.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    finally:
        conn.close()
