from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, or_, select

from app.models.opportunity_lineage import OpportunityLineage


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _load(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def record_lineage(
    session: Session,
    *,
    from_kind: str,
    from_id: str,
    to_kind: str,
    to_id: str,
    relation: str = "derived",
    context: dict[str, Any] | None = None,
    score: float | None = None,
) -> OpportunityLineage | None:
    source_kind = str(from_kind or "").strip().lower()
    source_id = str(from_id or "").strip()
    target_kind = str(to_kind or "").strip().lower()
    target_id = str(to_id or "").strip()
    if not source_kind or not source_id or not target_kind or not target_id:
        return None

    existing = session.exec(
        select(OpportunityLineage)
        .where(OpportunityLineage.from_kind == source_kind)
        .where(OpportunityLineage.from_id == source_id)
        .where(OpportunityLineage.to_kind == target_kind)
        .where(OpportunityLineage.to_id == target_id)
        .where(OpportunityLineage.relation == relation)
        .order_by(OpportunityLineage.created_at.desc())
    ).first()
    if existing:
        merged = _load(existing.context_json)
        merged.update(context or {})
        existing.context_json = _dump(merged)
        if score is not None:
            existing.score = score
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    row = OpportunityLineage(
        id=uuid.uuid4().hex,
        from_kind=source_kind,
        from_id=source_id,
        to_kind=target_kind,
        to_id=target_id,
        relation=str(relation or "derived").strip().lower() or "derived",
        context_json=_dump(context or {}),
        score=score,
        created_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_lineage_for_node(session: Session, *, kind: str, node_id: str) -> list[dict[str, Any]]:
    normalized_kind = str(kind or "").strip().lower()
    normalized_id = str(node_id or "").strip()
    if not normalized_kind or not normalized_id:
        return []
    rows = session.exec(
        select(OpportunityLineage)
        .where(
            or_(
                (OpportunityLineage.from_kind == normalized_kind) & (OpportunityLineage.from_id == normalized_id),
                (OpportunityLineage.to_kind == normalized_kind) & (OpportunityLineage.to_id == normalized_id),
            )
        )
        .order_by(OpportunityLineage.created_at.desc())
        .limit(500)
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "from_kind": row.from_kind,
                "from_id": row.from_id,
                "to_kind": row.to_kind,
                "to_id": row.to_id,
                "relation": row.relation,
                "context": _load(row.context_json),
                "score": row.score,
                "created_at": row.created_at.isoformat(),
            }
        )
    return out
