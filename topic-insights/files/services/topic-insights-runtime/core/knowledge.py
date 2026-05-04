from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from knowledge_layer import KnowledgeClient, KnowledgeConfig, build_record, should_write_record


@lru_cache(maxsize=1)
def get_knowledge_client() -> KnowledgeClient:
    return KnowledgeClient(KnowledgeConfig.from_env(spool_dir=str((ROOT_DIR / "data" / "knowledge").resolve())))


def search_context(query: str, *, domain: str, limit: int = 3) -> list[dict[str, Any]]:
    return get_knowledge_client().search(query, filters={"domain": domain}, limit=limit)


def format_context(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows[:5]:
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip()
        if not title and not summary:
            continue
        lines.append(f"- {title}: {summary}".strip(": "))
    return "\n".join(lines)


def maybe_add_record(payload: dict[str, Any], *, confidence: float | None, usefulness: float | None, reusable: bool = True) -> dict[str, Any]:
    client = get_knowledge_client()
    if not should_write_record(
        confidence=confidence,
        usefulness=usefulness,
        min_confidence=client.config.min_confidence,
        min_usefulness=client.config.min_usefulness,
        reusable=reusable,
    ):
        return {"ok": True, "skipped": True, "reason": "quality_gate"}
    return client.add_record(build_record(payload))
