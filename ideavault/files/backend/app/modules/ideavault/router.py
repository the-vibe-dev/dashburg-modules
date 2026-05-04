from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.ideavault import IdeaVaultItem, TopicFactoryQueueItem
from app.services.opportunity_lineage import list_lineage_for_node, record_lineage
from app.modules.topic_proxy.service import TopicProxyError, get_topic_proxy_service
from app.schemas.ideavault import (
    IdeaVaultCreate,
    IdeaVaultImportFromSource,
    IdeaVaultPatch,
    IdeaVaultRead,
    IdeaVaultReorderRequest,
    TopicFactoryQueueCreate,
    TopicFactoryQueuePatch,
    TopicFactoryQueueRead,
)

router = APIRouter(tags=["ideavault"])

IDEA_STATUSES = {"new", "queued", "researching", "ready", "shipped", "archived"}
IDEA_TYPES = {"trend", "topic", "idea"}
QUEUE_STATUSES = {"queued", "running", "done", "failed", "canceled"}


def _now() -> datetime:
    return datetime.utcnow()


def _json_load(raw: str, default: Any) -> Any:
    try:
        out = json.loads(raw or "")
        return out if isinstance(out, type(default)) else default
    except json.JSONDecodeError:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _queue_lookup(session: Session, idea_ids: list[str] | None = None) -> dict[str, TopicFactoryQueueItem]:
    if not idea_ids:
        return {}
    rows = session.exec(
        select(TopicFactoryQueueItem)
        .where(TopicFactoryQueueItem.ideavault_item_id.in_(idea_ids))
        .order_by(TopicFactoryQueueItem.created_at.desc())
    ).all()
    by_idea: dict[str, TopicFactoryQueueItem] = {}
    for row in rows:
        if row.ideavault_item_id and row.ideavault_item_id not in by_idea:
            by_idea[row.ideavault_item_id] = row
    return by_idea


def _to_idea_read(row: IdeaVaultItem, queue: TopicFactoryQueueItem | None, include_payload: bool = True) -> IdeaVaultRead:
    source = _json_load(row.source_json, {})
    payload = _json_load(row.payload_json, {}) if include_payload else {}
    run_id = str(source.get("run_id") or source.get("source_run_id") or "").strip()
    next_actions = [
        {"label": "Open in IdeaVault", "href": f"/modules/ideavault?item_id={row.id}", "kind": "review"},
        {"label": "Open IdeaFactory", "href": f"/modules/appgen{f'?run_id={run_id}' if run_id else ''}", "kind": "research"},
        {"label": "Open TopicInsights", "href": "/modules/topic-insights", "kind": "insight"},
        {"label": "Open TrendsResearcher", "href": f"/modules/trends?query={row.title}", "kind": "research"},
    ]
    return IdeaVaultRead(
        id=row.id,
        title=row.title,
        summary=row.summary,
        type=row.type,
        status=row.status,
        tags=_json_load(row.tags_json, []),
        source=source,
        payload=payload,
        score=row.score,
        pinned=row.pinned,
        priority_rank=row.priority_rank,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_touched_at=row.last_touched_at,
        queue_entry_id=queue.id if queue else None,
        queue_status=queue.status if queue else None,
        next_actions=next_actions,
    )


def _record_item_lineage(session: Session, item: IdeaVaultItem) -> None:
    source = _json_load(item.source_json, {})
    module = str(source.get("module") or "").strip().lower()
    run_id = str(source.get("run_id") or source.get("source_run_id") or "").strip()
    topic_id = str(source.get("topic_id") or source.get("trend_topic_id") or "").strip()
    idea_id = str(source.get("idea_id") or source.get("source_idea_id") or "").strip()
    signal_id = str(source.get("signal_id") or "").strip()
    cluster_id = str(source.get("cluster_id") or source.get("group_id") or source.get("call_id") or "").strip()
    idea_type = str(source.get("idea_type") or _json_load(item.payload_json, {}).get("idea_type") or "").strip().lower()
    context = {
        "module": source.get("module"),
        "run_id": run_id or None,
        "topic_id": topic_id or None,
        "idea_id": idea_id or None,
        "idea_type": idea_type or None,
        "item_type": item.type,
    }
    if module in {"trendsresearcher", "trends"}:
        if run_id:
            record_lineage(
                session,
                from_kind="trends_run",
                from_id=run_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="saved",
                context=context,
                score=item.score,
            )
        if topic_id:
            record_lineage(
                session,
                from_kind="trend_topic",
                from_id=topic_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="promoted",
                context=context,
                score=item.score,
            )
    elif module in {"topicinsights", "topic_insights"}:
        if run_id:
            record_lineage(
                session,
                from_kind="topic_run",
                from_id=run_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="promoted",
                context=context,
                score=item.score,
            )
        if cluster_id:
            record_lineage(
                session,
                from_kind="topic_cluster",
                from_id=cluster_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="derived",
                context=context,
                score=item.score,
            )
    elif module in {"ideafactory", "appgen"}:
        if run_id:
            record_lineage(
                session,
                from_kind="ideafactory_run",
                from_id=run_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="promoted",
                context=context,
                score=item.score,
            )
        if idea_id:
            record_lineage(
                session,
                from_kind=f"opportunity_{idea_type or 'generic'}",
                from_id=idea_id,
                to_kind="ideavault_item",
                to_id=item.id,
                relation="selected",
                context=context,
                score=item.score,
            )
    else:
        for from_kind, from_id in (
            ("source_run", run_id),
            ("source_topic", topic_id),
            ("source_idea", idea_id),
            ("source_signal", signal_id),
        ):
            if from_id:
                record_lineage(
                    session,
                    from_kind=from_kind,
                    from_id=from_id,
                    to_kind="ideavault_item",
                    to_id=item.id,
                    relation="saved",
                    context=context,
                    score=item.score,
                )


def _to_queue_read(row: TopicFactoryQueueItem) -> TopicFactoryQueueRead:
    return TopicFactoryQueueRead(
        id=row.id,
        topic_text=row.topic_text,
        source=_json_load(row.source_json, {}),
        ideavault_item_id=row.ideavault_item_id,
        status=row.status,
        run_id=row.run_id,
        params=_json_load(row.params_json, {}),
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _priority_sort_key(item: IdeaVaultItem) -> tuple[int, datetime]:
    rank = item.priority_rank if item.priority_rank is not None else 10_000_000
    pin_bias = 0 if item.pinned else 1
    return (pin_bias, rank, item.created_at)


def _normalize_priority(session: Session) -> None:
    rows = session.exec(select(IdeaVaultItem).where(IdeaVaultItem.deleted == False)).all()  # noqa: E712
    ordered = sorted(rows, key=_priority_sort_key)
    changed = False
    for idx, row in enumerate(ordered):
        if row.priority_rank != idx:
            row.priority_rank = idx
            row.updated_at = _now()
            session.add(row)
            changed = True
    if changed:
        session.commit()


@router.get("/api/ideavault/items", response_model=list[IdeaVaultRead])
def list_ideavault_items(
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    pinned: bool | None = Query(default=None),
    sort: str = Query(default="priority"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_payload: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> list[IdeaVaultRead]:
    stmt = select(IdeaVaultItem).where(IdeaVaultItem.deleted == False)  # noqa: E712

    if search:
        q = search.lower().strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(func.lower(IdeaVaultItem.title).like(like), func.lower(IdeaVaultItem.summary).like(like)))
    if status:
        stmt = stmt.where(IdeaVaultItem.status == status)
    if type:
        stmt = stmt.where(IdeaVaultItem.type == type)
    if pinned is not None:
        stmt = stmt.where(IdeaVaultItem.pinned == pinned)
    if tag:
        t = tag.lower().strip()
        if t:
            stmt = stmt.where(func.lower(IdeaVaultItem.tags_json).like(f'%"{t}"%'))

    if sort == "oldest":
        stmt = stmt.order_by(IdeaVaultItem.created_at.asc())
    elif sort == "score":
        stmt = stmt.order_by(func.coalesce(IdeaVaultItem.score, -1).desc(), IdeaVaultItem.created_at.desc())
    else:
        if sort == "newest":
            stmt = stmt.order_by(IdeaVaultItem.created_at.desc())
        else:
            stmt = stmt.order_by(
                IdeaVaultItem.pinned.desc(),
                func.coalesce(IdeaVaultItem.priority_rank, 10_000_000).asc(),
                IdeaVaultItem.created_at.asc(),
            )

    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    queue_map = _queue_lookup(session, [r.id for r in rows])
    return [_to_idea_read(r, queue_map.get(r.id), include_payload=include_payload) for r in rows]


@router.post("/api/ideavault/items", response_model=IdeaVaultRead)
def create_ideavault_item(payload: IdeaVaultCreate, session: Session = Depends(get_session)) -> IdeaVaultRead:
    if payload.type not in IDEA_TYPES:
        raise HTTPException(status_code=400, detail="invalid type")
    desired_status = payload.status or "new"
    if desired_status not in IDEA_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")

    max_rank = session.exec(select(IdeaVaultItem.priority_rank).order_by(IdeaVaultItem.priority_rank.desc())).first()
    next_rank = int(max_rank) + 1 if max_rank is not None else 0
    now = _now()
    row = IdeaVaultItem(
        id=uuid.uuid4().hex,
        title=payload.title.strip(),
        summary=(payload.summary or "").strip(),
        type=payload.type,
        status=desired_status,
        tags_json=_json_dump(payload.tags),
        source_json=_json_dump(payload.source),
        payload_json=_json_dump(payload.payload),
        score=payload.score,
        pinned=payload.pinned,
        priority_rank=next_rank,
        created_at=now,
        updated_at=now,
        last_touched_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    _record_item_lineage(session, row)
    return _to_idea_read(row, None)


@router.get("/api/ideavault/items/{item_id}", response_model=IdeaVaultRead)
def get_ideavault_item(item_id: str, session: Session = Depends(get_session)) -> IdeaVaultRead:
    row = session.get(IdeaVaultItem, item_id)
    if not row or row.deleted:
        raise HTTPException(status_code=404, detail="item not found")
    queue = session.exec(
        select(TopicFactoryQueueItem)
        .where(TopicFactoryQueueItem.ideavault_item_id == row.id)
        .order_by(TopicFactoryQueueItem.created_at.desc())
    ).first()
    return _to_idea_read(row, queue)


@router.get("/api/ideavault/items/{item_id}/lineage")
def ideavault_item_lineage(item_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(IdeaVaultItem, item_id)
    if not row or row.deleted:
        raise HTTPException(status_code=404, detail="item not found")
    edges = list_lineage_for_node(session, kind="ideavault_item", node_id=item_id)
    return {"item_id": item_id, "edges": edges, "count": len(edges)}


@router.get("/api/lineage/trace")
def lineage_trace(
    kind: str = Query(..., min_length=1),
    node_id: str = Query(..., alias="id", min_length=1),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    edges = list_lineage_for_node(session, kind=kind, node_id=node_id)
    return {"kind": kind, "id": node_id, "edges": edges, "count": len(edges)}


@router.patch("/api/ideavault/items/{item_id}", response_model=IdeaVaultRead)
def patch_ideavault_item(item_id: str, payload: IdeaVaultPatch, session: Session = Depends(get_session)) -> IdeaVaultRead:
    row = session.get(IdeaVaultItem, item_id)
    if not row or row.deleted:
        raise HTTPException(status_code=404, detail="item not found")

    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.summary is not None:
        row.summary = payload.summary.strip()
    if payload.status is not None:
        if payload.status not in IDEA_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        row.status = payload.status
    if payload.tags is not None:
        row.tags_json = _json_dump(payload.tags)
    if payload.source is not None:
        row.source_json = _json_dump(payload.source)
    if payload.payload is not None:
        row.payload_json = _json_dump(payload.payload)
    if payload.score is not None:
        row.score = payload.score
    if payload.pinned is not None:
        row.pinned = payload.pinned
    if payload.priority_rank is not None:
        row.priority_rank = payload.priority_rank

    row.updated_at = _now()
    row.last_touched_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)

    queue = session.exec(
        select(TopicFactoryQueueItem)
        .where(TopicFactoryQueueItem.ideavault_item_id == row.id)
        .order_by(TopicFactoryQueueItem.created_at.desc())
    ).first()
    return _to_idea_read(row, queue)


@router.delete("/api/ideavault/items/{item_id}")
def delete_ideavault_item(item_id: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    row = session.get(IdeaVaultItem, item_id)
    if not row or row.deleted:
        raise HTTPException(status_code=404, detail="item not found")
    row.deleted = True
    row.status = "archived"
    row.updated_at = _now()
    row.last_touched_at = _now()
    session.add(row)
    session.commit()
    return {"ok": True}


@router.post("/api/ideavault/items/reorder")
def reorder_ideavault_items(payload: IdeaVaultReorderRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    ids = payload.orderedIds
    if not ids:
        return {"ok": True, "count": 0}
    _normalize_priority(session)

    all_rows = session.exec(select(IdeaVaultItem).where(IdeaVaultItem.deleted == False)).all()  # noqa: E712
    by_id = {r.id: r for r in all_rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    remaining = [r for r in sorted(all_rows, key=_priority_sort_key) if r.id not in set(ids)]
    merged = ordered + remaining

    for idx, row in enumerate(merged):
        row.priority_rank = idx
        row.updated_at = _now()
        session.add(row)
    session.commit()
    return {"ok": True, "count": len(ids)}


@router.post("/api/ideavault/import/from-topicfactory")
def import_from_topicfactory(payload: IdeaVaultImportFromSource, session: Session = Depends(get_session)) -> dict[str, Any]:
    created: list[str] = []
    for item in payload.items:
        row = create_ideavault_item(item, session)
        created.append(row.id)
    return {"ok": True, "created_ids": created}


@router.post("/api/ideavault/import/from-trends")
def import_from_trends(payload: IdeaVaultImportFromSource, session: Session = Depends(get_session)) -> dict[str, Any]:
    return import_from_topicfactory(payload, session)


@router.get("/api/topic/queue", response_model=list[TopicFactoryQueueRead])
@router.get("/api/topicfactory/queue", response_model=list[TopicFactoryQueueRead])
def list_topicfactory_queue(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[TopicFactoryQueueRead]:
    rows = session.exec(select(TopicFactoryQueueItem).order_by(TopicFactoryQueueItem.created_at.desc()).limit(limit)).all()
    return [_to_queue_read(r) for r in rows]


@router.post("/api/topic/queue", response_model=TopicFactoryQueueRead)
@router.post("/api/topicfactory/queue", response_model=TopicFactoryQueueRead)
def enqueue_topicfactory(payload: TopicFactoryQueueCreate, session: Session = Depends(get_session)) -> TopicFactoryQueueRead:
    now = _now()
    row = TopicFactoryQueueItem(
        id=uuid.uuid4().hex,
        topic_text=payload.topic_text.strip(),
        source_json=_json_dump(payload.source),
        ideavault_item_id=payload.ideavault_item_id,
        status="queued",
        params_json=_json_dump(payload.params),
        created_at=now,
        updated_at=now,
    )
    session.add(row)

    if payload.ideavault_item_id:
        idea = session.get(IdeaVaultItem, payload.ideavault_item_id)
        if idea and not idea.deleted:
            idea.status = "queued"
            idea.last_touched_at = now
            idea.updated_at = now
            session.add(idea)

    session.commit()
    session.refresh(row)
    return _to_queue_read(row)


@router.patch("/api/topic/queue/{queue_id}", response_model=TopicFactoryQueueRead)
@router.patch("/api/topicfactory/queue/{queue_id}", response_model=TopicFactoryQueueRead)
def patch_topicfactory_queue(queue_id: str, payload: TopicFactoryQueuePatch, session: Session = Depends(get_session)) -> TopicFactoryQueueRead:
    row = session.get(TopicFactoryQueueItem, queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")

    if payload.status is not None:
        if payload.status not in QUEUE_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        row.status = payload.status
        if payload.status == "running":
            row.started_at = _now()
        if payload.status in {"done", "failed", "canceled"}:
            row.finished_at = _now()

    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_queue_read(row)


@router.post("/api/topic/queue/{queue_id}/cancel", response_model=TopicFactoryQueueRead)
@router.post("/api/topicfactory/queue/{queue_id}/cancel", response_model=TopicFactoryQueueRead)
def cancel_topicfactory_queue(queue_id: str, session: Session = Depends(get_session)) -> TopicFactoryQueueRead:
    return patch_topicfactory_queue(queue_id, TopicFactoryQueuePatch(status="canceled"), session)


@router.delete("/api/topic/queue/{queue_id}")
@router.delete("/api/topicfactory/queue/{queue_id}")
def delete_topicfactory_queue(queue_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = session.get(TopicFactoryQueueItem, queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")

    idea = session.get(IdeaVaultItem, row.ideavault_item_id) if row.ideavault_item_id else None
    session.delete(row)

    if idea and not idea.deleted and idea.status == "queued":
        idea.status = "new"
        idea.updated_at = _now()
        idea.last_touched_at = _now()
        session.add(idea)

    session.commit()
    return {"ok": True, "id": queue_id, "deleted": True}


@router.post("/api/topic/queue/{queue_id}/start", response_model=TopicFactoryQueueRead)
@router.post("/api/topicfactory/queue/{queue_id}/start", response_model=TopicFactoryQueueRead)
async def start_topicfactory_queue(queue_id: str, session: Session = Depends(get_session)) -> TopicFactoryQueueRead:
    row = session.get(TopicFactoryQueueItem, queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")

    row.status = "running"
    row.started_at = _now()
    row.updated_at = _now()
    session.add(row)
    session.commit()

    params = _json_load(row.params_json, {})
    topic_text = row.topic_text
    topic_service = get_topic_proxy_service()
    try:
        body = {
            "query": topic_text,
            "topic": topic_text,
            "limit": int(params.get("limit", 20)),
            "enable_youtube": bool(params.get("enable_youtube", False)),
        }
        resp = await topic_service.request("POST", "/runs/targeted", json_body=body)
        run_id = str(resp.get("run_id") or resp.get("id") or "") if isinstance(resp, dict) else ""
        row.run_id = run_id or None
        row.status = "done"
        row.finished_at = _now()
        row.error = None
    except TopicProxyError as exc:
        row.status = "failed"
        row.finished_at = _now()
        row.error = f"{exc.message} (upstream_status={exc.upstream_status})"
    except Exception as exc:  # noqa: BLE001
        row.status = "failed"
        row.finished_at = _now()
        row.error = str(exc)

    row.updated_at = _now()
    session.add(row)

    if row.ideavault_item_id:
        idea = session.get(IdeaVaultItem, row.ideavault_item_id)
        if idea and not idea.deleted:
            idea.status = "researching" if row.status == "running" else ("ready" if row.status == "done" else "queued")
            idea.last_touched_at = _now()
            idea.updated_at = _now()
            session.add(idea)

    session.commit()
    session.refresh(row)
    return _to_queue_read(row)
