from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable
from appgen.config import load_config

TEXT_HINTS = ("name", "title", "subject", "summary", "body", "content", "text", "post", "comment")


def find_oie_db() -> Path | None:
    cfg = load_config()["appgen"]["pain_sources"]
    for p in cfg.get("oie_db_path_candidates", []):
        path = Path(p)
        if path.exists() and path.is_file():
            return path
    return None


def extract_from_oie(limit: int = 200) -> list[dict]:
    db = find_oie_db()
    if not db:
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: list[dict] = []
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in tables:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_names = [c[1] for c in cols]
            text_cols = [c for c in col_names if any(h in c.lower() for h in TEXT_HINTS)]
            if not text_cols:
                continue
            pk_col = col_names[0] if col_names else "rowid"
            query = f"SELECT {pk_col} as _pk, {', '.join(text_cols[:3])} FROM {t} LIMIT 50"
            try:
                rows = conn.execute(query).fetchall()
            except Exception:
                continue
            for r in rows:
                parts = [str(r[c]).strip() for c in text_cols[:3] if r[c] is not None and str(r[c]).strip()]
                if not parts:
                    continue
                text = "\n".join(parts)[:2000]
                out.append({"source_type": "oie_db", "source_ref": f"oie:{t}:{r['_pk']}", "text": text})
                if len(out) >= limit:
                    return out
    finally:
        conn.close()
    return out
