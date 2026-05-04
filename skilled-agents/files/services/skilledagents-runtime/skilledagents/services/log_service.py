from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class LogService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def append(self, agent_id: str, run_id: str | None, level: str, message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_logs(id, agent_id, run_id, level, message, created_at)
                VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?)
                """,
                (agent_id, run_id, level, message, now),
            )
            conn.commit()

    def get_logs(self, agent_id: str, limit: int = 200, run_id: str | None = None) -> list[dict]:
        query = """
            SELECT id, agent_id, run_id, level, message, created_at
            FROM agent_logs
            WHERE agent_id = ?
        """
        params: list = [agent_id]
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
