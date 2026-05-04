from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
import logging

from core.config import settings
from extraction.llm import chat_json
from storage.models import ExtractedPain, RawPost

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "pain_extraction.md"


def extract_pain_from_text(text: str) -> dict:
    system = "You extract structured pain points from user-generated content."
    user = PROMPT_PATH.read_text(encoding="utf-8") + "\n\nCONTENT:\n" + text[: settings.llm_max_input_chars]
    return chat_json(system=system, user=user)


def _pack_posts(posts: list[RawPost], char_budget: int) -> list[RawPost]:
    """Pack posts into a single prompt budget.

    Prefer higher engagement first, then fill while deduping near-identical text starts.
    """
    ordered = sorted(posts, key=lambda p: int(p.engagement_score or 0), reverse=True)
    packed: list[RawPost] = []
    used = 0
    seen = set()
    for p in ordered:
        txt = (p.text or "").strip()
        if not txt:
            continue
        key = txt[:180].lower()
        if key in seen:
            continue
        seen.add(key)
        chunk = min(len(txt), max(400, char_budget // max(1, settings.llm_batch_size)))
        if used + chunk > char_budget and packed:
            break
        packed.append(p)
        used += chunk
        if len(packed) >= settings.llm_batch_size:
            break
    return packed


def extract_pains_from_posts(posts: list[RawPost], topic: str, run_id: str | None = None) -> list[ExtractedPain]:
    log = logging.getLogger(__name__)
    pains: list[ExtractedPain] = []
    batch_size = max(1, settings.llm_batch_size)
    prompt_base = PROMPT_PATH.read_text(encoding="utf-8")

    for start in range(0, len(posts), batch_size):
        batch = posts[start : start + batch_size]
        packed = _pack_posts(batch, settings.llm_max_input_chars)
        content_lines = []
        used = 0
        per_post_cap = max(1000, settings.llm_max_input_chars // max(1, len(packed)))
        for i, p in enumerate(packed):
            snippet = (p.text or "")[:per_post_cap]
            used += len(snippet)
            content_lines.append(f"{i}: {snippet}")

        system = "You extract structured pain points from user-generated content."
        user = (
            prompt_base
            + "\n\nReturn JSON only: {\"items\": [{\"index\": 0, \"pain_summary\": \"...\", \"emotional_intensity\": 0.0, \"frustration_keywords\": [], \"workaround_detected\": false, \"workaround_type\": null, \"existing_solution_mentions\": [], \"urgency_signal\": 0.0}]}\n\nCONTENT_LIST:\n"
            + "\n\n".join(content_lines)
        )
        try:
            data = chat_json(system=system, user=user)
        except Exception as e:
            log.exception("pain_extract_batch_failed start=%s packed=%s chars=%s error=%s", start, len(packed), used, e)
            continue

        items = data.get("items") or []
        for it in items:
            try:
                idx = int(it.get("index"))
                p = packed[idx]
            except Exception:
                continue
            pains.append(
                ExtractedPain(
                    pain_id=str(uuid.uuid4()),
                    run_id=run_id,
                    raw_post_id=p.id,
                    topic=topic,
                    pain_summary=str(it.get("pain_summary", "")).strip()[:300],
                    emotional_intensity=float(it.get("emotional_intensity", 0.0) or 0.0),
                    frustration_keywords=list(it.get("frustration_keywords") or []),
                    workaround_detected=bool(it.get("workaround_detected", False)),
                    workaround_type=it.get("workaround_type"),
                    existing_solution_mentions=list(it.get("existing_solution_mentions") or []),
                    urgency_signal=float(it.get("urgency_signal", 0.0) or 0.0),
                    created_at=datetime.utcnow(),
                )
            )
    return pains
