from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from appgen.repo import (
    get_idea as appgen_get_idea,
    get_run as appgen_get_run,
    list_ideas as appgen_list_ideas,
    list_outbox as appgen_list_outbox,
    list_runs as appgen_list_runs,
)
from core.config import settings
from core.orchestrator import RunParams, run_auto_discovery, run_end_to_end
from storage.db import get_session
from storage.models import ExtractedPain, Idea, PainCluster, RawPost
from storage.repository import (
    find_pains_for_cluster_label,
    get_cluster,
    get_counts,
    get_idea,
    get_run_events_by_run_id,
    list_clusters,
    list_ideas,
    list_pains,
    list_run_events,
    provider_stats,
    provider_stats_for_run,
)

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class HealthOut(BaseModel):
    status: str
    version: str
    time: str
    db_path: str


class TargetedRunIn(BaseModel):
    query: str
    topic: str
    limit: int = 40
    enable_youtube: bool = False
    sources: dict[str, bool] | None = None
    sources_config: dict[str, dict[str, Any]] | None = None
    ingest_overrides: dict[str, int] | None = None
    category_mode: str = "broad"
    category_filters: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)


class AutoRunIn(BaseModel):
    ideas_per_run: int = 5
    target_topics: int = 20
    limit_per_topic: int = 30
    ingest_overrides: dict[str, int] | None = None
    category_mode: str = "broad"
    category_filters: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)


class RunQueuedOut(BaseModel):
    run_id: str
    status: str


_JOB_LOCK = threading.Lock()
_RUN_JOBS: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _keyword_top(pains: list[ExtractedPain], n: int = 6) -> list[str]:
    c = Counter()
    for p in pains:
        for k in (p.frustration_keywords or [])[:8]:
            if k:
                c[str(k).strip().lower()] += 1
    return [k for k, _ in c.most_common(n)]


def _run_time_bounds(events: list[Any]) -> tuple[datetime | None, datetime | None]:
    if not events:
        return None, None
    stamps = [e.created_at for e in events if getattr(e, "created_at", None) is not None]
    if not stamps:
        return None, None
    start = min(stamps) - timedelta(minutes=2)
    end = max(stamps) + timedelta(minutes=20)
    return start, end


def _time_window_rows(
    model: Any,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    topic: str | None = None,
) -> list[Any]:
    with get_session() as s:
        q = select(model)
        if start:
            q = q.where(model.created_at >= start)
        if end:
            q = q.where(model.created_at <= end)
        if topic and hasattr(model, "topic"):
            q = q.where(model.topic == topic)
        order_col = model.opportunity_score.desc() if hasattr(model, "opportunity_score") else model.created_at.desc()
        q = q.order_by(order_col).limit(limit)
        return list(s.exec(q))


def _start_job(job_id: str, kind: str, fn, *args, **kwargs) -> None:
    def _runner() -> None:
        log = logging.getLogger(__name__)
        with _JOB_LOCK:
            _RUN_JOBS[job_id]["status"] = "running"
            _RUN_JOBS[job_id]["started_at"] = _utc_now()
        try:
            result = fn(*args, **kwargs)
            with _JOB_LOCK:
                _RUN_JOBS[job_id]["status"] = "completed"
                _RUN_JOBS[job_id]["finished_at"] = _utc_now()
                _RUN_JOBS[job_id]["result"] = result
                if isinstance(result, dict) and result.get("run_id"):
                    _RUN_JOBS[job_id]["pipeline_run_id"] = result["run_id"]
        except Exception as exc:
            log.exception("api_v1_job_failed kind=%s job_id=%s error=%s", kind, job_id, exc)
            with _JOB_LOCK:
                _RUN_JOBS[job_id]["status"] = "failed"
                _RUN_JOBS[job_id]["finished_at"] = _utc_now()
                _RUN_JOBS[job_id]["error"] = str(exc)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        status="ok",
        version="v1",
        time=_utc_now(),
        db_path=settings.database_url,
    )


@router.get("/topics/trending")
def trending_topics(limit: int = 20):
    pains = list_pains(limit=2000)
    by_topic: dict[str, list[ExtractedPain]] = defaultdict(list)
    for p in pains:
        topic = (p.topic or "").strip()
        if topic:
            by_topic[topic].append(p)

    topic_rows = []
    for topic, items in by_topic.items():
        last_seen = max((x.created_at for x in items), default=None)
        raw_ids = [x.raw_post_id for x in items[:400] if x.raw_post_id]
        source_counts: Counter[str] = Counter()
        if raw_ids:
            with get_session() as s:
                rows = list(s.exec(select(RawPost).where(RawPost.id.in_(raw_ids))))
            for r in rows:
                source_counts[r.source] += 1
        topic_rows.append(
            {
                "topic": topic,
                "pain_count": len(items),
                "last_seen": last_seen.isoformat() if last_seen else None,
                "top_sources": [k for k, _ in source_counts.most_common(3)],
                "top_keywords": _keyword_top(items),
            }
        )

    topic_rows.sort(key=lambda x: (x["pain_count"], x["last_seen"] or ""), reverse=True)
    return {"items": topic_rows[: max(1, limit)]}


@router.get("/trending")
def trending_alias(limit: int = 20):
    # Backward-compatible alias for Dashburg clients expecting /api/v1/trending.
    return trending_topics(limit=limit)


@router.get("/clusters")
def clusters(limit: int = 50, run_id: str | None = None):
    return {"items": [c.model_dump() for c in list_clusters(limit=limit, run_id=run_id)]}


@router.get("/clusters/{cluster_id}")
def cluster_detail(cluster_id: str):
    c = get_cluster(cluster_id)
    if not c:
        raise HTTPException(status_code=404, detail="cluster not found")
    pains = find_pains_for_cluster_label(c.cluster_label, limit=30)
    ideas = list_ideas(cluster_id=cluster_id, limit=50)
    return {
        "cluster": c.model_dump(),
        "top_pains": [p.model_dump() for p in pains],
        "ideas": [i.model_dump() for i in ideas],
    }


@router.get("/ideas")
def ideas(cluster_id: str | None = None, limit: int = 100, run_id: str | None = None):
    return {"items": [i.model_dump() for i in list_ideas(cluster_id=cluster_id, limit=limit, run_id=run_id)]}


@router.get("/ideas/{idea_id}")
def idea_detail(idea_id: str):
    i = get_idea(idea_id)
    if not i:
        raise HTTPException(status_code=404, detail="idea not found")
    return i.model_dump()


@router.get("/pains")
def pains(topic: str | None = None, cluster_id: str | None = None, limit: int = 200, run_id: str | None = None):
    if cluster_id:
        c = get_cluster(cluster_id)
        if not c:
            raise HTTPException(status_code=404, detail="cluster not found")
        rows = find_pains_for_cluster_label(c.cluster_label, limit=limit)
        return {"items": [p.model_dump() for p in rows]}
    rows = list_pains(topic=topic, limit=limit, run_id=run_id)
    return {"items": [p.model_dump() for p in rows]}


@router.post("/runs/targeted", response_model=RunQueuedOut)
def run_targeted(body: TargetedRunIn):
    run_id = str(uuid.uuid4())
    with _JOB_LOCK:
        _RUN_JOBS[run_id] = {
            "run_id": run_id,
            "kind": "targeted",
            "status": "queued",
            "created_at": _utc_now(),
            "input": body.model_dump(),
        }

    _start_job(
        run_id,
        "targeted",
        run_end_to_end,
        RunParams(
            query=body.query,
            topic=body.topic,
            limit=body.limit,
            enable_youtube=body.enable_youtube,
            sources=body.sources,
            sources_config=body.sources_config,
            ingest_overrides=body.ingest_overrides,
            category_mode=body.category_mode,
            category_filters=body.category_filters,
            exclude_categories=body.exclude_categories,
        ),
    )
    return RunQueuedOut(run_id=run_id, status="queued")


@router.post("/runs/start")
def run_start_compat(body: TargetedRunIn):
    queued = run_targeted(body)
    return {"run_id": queued.run_id, "status": queued.status}


@router.post("/runs/auto", response_model=RunQueuedOut)
def run_auto(body: AutoRunIn):
    run_id = str(uuid.uuid4())
    with _JOB_LOCK:
        _RUN_JOBS[run_id] = {
            "run_id": run_id,
            "kind": "auto",
            "status": "queued",
            "created_at": _utc_now(),
            "input": body.model_dump(),
        }
    _start_job(
        run_id,
        "auto",
        run_auto_discovery,
        body.ideas_per_run,
        body.target_topics,
        body.limit_per_topic,
        body.ingest_overrides,
    )
    return RunQueuedOut(run_id=run_id, status="queued")


@router.get("/runs")
def runs(limit: int = 50):
    events = [e.model_dump() for e in list_run_events(limit=limit)]
    with _JOB_LOCK:
        jobs = list(_RUN_JOBS.values())
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:limit], "events": events}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    with _JOB_LOCK:
        job = _RUN_JOBS.get(run_id)

    pipeline_run_id = run_id
    if job and job.get("pipeline_run_id"):
        pipeline_run_id = job["pipeline_run_id"]

    evs = get_run_events_by_run_id(pipeline_run_id, limit=500)
    call_rows = provider_stats_for_run(pipeline_run_id, limit=500)
    if not evs and not job:
        raise HTTPException(status_code=404, detail="run not found")

    counts = {
        "stages": len(evs),
        "providers": len(call_rows),
        "raw_posts": 0,
        "pains": 0,
        "clusters": 0,
        "ideas": 0,
    }
    for e in evs:
        if e.stage_name == "ingest":
            counts["raw_posts"] = max(counts["raw_posts"], e.output_count)
        elif e.stage_name == "extract":
            counts["pains"] = max(counts["pains"], e.output_count)
        elif e.stage_name == "score":
            counts["clusters"] = max(counts["clusters"], e.output_count)
        elif e.stage_name == "ideas":
            counts["ideas"] = max(counts["ideas"], e.output_count)

    topic_hint = None
    if isinstance((job or {}).get("input"), dict):
        topic_hint = str((job or {}).get("input", {}).get("topic") or "").strip() or None

    run_clusters = list_clusters(limit=20, run_id=pipeline_run_id)
    run_ideas = list_ideas(limit=20, run_id=pipeline_run_id)
    run_pains = list_pains(limit=80, topic=topic_hint, run_id=pipeline_run_id)
    if not run_pains:
        run_pains = list_pains(limit=80, run_id=pipeline_run_id)

    # Backward-compatible fallback for older runs created before run_id lineage columns.
    if not run_clusters and not run_ideas and not run_pains:
        win_start, win_end = _run_time_bounds(evs)
        run_clusters = _time_window_rows(PainCluster, start=win_start, end=win_end, limit=20)
        run_ideas = _time_window_rows(Idea, start=win_start, end=win_end, limit=20)
        run_pains = _time_window_rows(ExtractedPain, start=win_start, end=win_end, limit=80, topic=topic_hint)

    cluster_rows = [c.model_dump() for c in run_clusters]
    idea_rows = [i.model_dump() for i in run_ideas]
    pain_rows = [p.model_dump() for p in run_pains[:50]]

    raw_post_ids = [p.raw_post_id for p in run_pains if p.raw_post_id]
    source_rows: list[RawPost] = []
    if raw_post_ids:
        with get_session() as s:
            source_rows = list(s.exec(select(RawPost).where(RawPost.id.in_(raw_post_ids[:300]))))
    signal_rows = [r.model_dump() for r in source_rows[:60]]

    provider_summary: dict[str, dict[str, Any]] = {}
    for c in call_rows:
        info = provider_summary.setdefault(c.provider, {"calls": 0, "errors": 0, "cache_hits": 0})
        info["calls"] += 1
        info["errors"] += 0 if c.success else 1
        info["cache_hits"] += 1 if c.cache_hit else 0

    return {
        "run_id": run_id,
        "pipeline_run_id": pipeline_run_id,
        "status": (job or {}).get("status", "completed" if evs else "unknown"),
        "job": job,
        "counts": counts,
        "run_events": [e.model_dump() for e in evs],
        "provider_stats": provider_summary,
        "outputs": {
            "clusters": cluster_rows,
            "ideas": idea_rows,
            "top_pains": pain_rows,
            "signals": signal_rows,
            "report_paths": (job or {}).get("result", {}).get("reports", {}),
        },
        "totals_json": {
            "source_candidate_counts": ((job or {}).get("result", {}) or {}).get("source_counts", {}),
            "category_candidate_counts": ((job or {}).get("result", {}) or {}).get("category_counts", {}),
            "source_warnings": ((job or {}).get("result", {}) or {}).get("warnings", []),
        },
    }


@router.get("/runs/{run_id}/results")
def run_results(run_id: str, limit: int = 25):
    detail = run_detail(run_id)
    clusters = ((detail.get("outputs") or {}).get("clusters") or [])[: max(1, limit)]
    top_overall: list[dict[str, Any]] = []

    for c in clusters:
        title = str(c.get("cluster_label") or "")
        pains = find_pains_for_cluster_label(title, limit=50)
        raw_ids = [p.raw_post_id for p in pains if p.raw_post_id]
        source_counts: Counter[str] = Counter()
        source_details: dict[str, Any] = {}
        if raw_ids:
            with get_session() as s:
                rows = list(s.exec(select(RawPost).where(RawPost.id.in_(raw_ids))))
            for row in rows:
                src = str(row.source or "")
                if not src:
                    continue
                source_counts[src] += 1
                if src == "x" and src not in source_details:
                    metrics = (row.metadata_ or {}).get("metrics") or {}
                    source_details["x"] = {
                        "rank": metrics.get("rank"),
                        "category": metrics.get("category"),
                        "post_count_text": metrics.get("post_count_text"),
                    }
        sources = list(source_counts.keys())
        emerging = bool(sources) and set(sources) == {"x"}
        top_overall.append(
            {
                "topic_id": c.get("cluster_id"),
                "title": title,
                "score": float(c.get("opportunity_score") or 0.0),
                "sources": sources,
                "source_details": source_details,
                "source_confidence": "medium" if "x" in sources else "low",
                "emerging_on_x": emerging,
            }
        )

    return {
        "run_id": run_id,
        "top_overall": top_overall[: max(1, limit)],
        "top_per_channel": {},
        "totals_json": detail.get("totals_json", {}),
    }


@router.get("/providers/stats")
def providers_stats(limit: int = 200):
    rows = provider_stats(limit=limit)
    return {"items": [r.model_dump() for r in rows]}


@router.get("/logs/tail")
def logs_tail(offset: int = 0, max_lines: int = 200):
    log_path = Path(settings.data_dir) / "run.log"
    if not log_path.exists():
        return {"offset": 0, "lines": []}
    with log_path.open("r", encoding="utf-8") as f:
        try:
            size = log_path.stat().st_size
            if offset > size:
                offset = 0
        except Exception:
            pass
        f.seek(offset)
        chunk = f.read(80_000)
        new_offset = f.tell()
    lines = chunk.splitlines()[: max_lines]
    return {"offset": new_offset, "lines": lines}


@router.get("/appgen/ideas")
def appgen_ideas(status: str | None = None, q: str | None = None, sort: str = "updated_desc", needs_scoring: bool | None = None, imported: bool | None = None, category: str | None = None):
    return {"items": appgen_list_ideas(status=status, q=q, sort=sort, needs_scoring=needs_scoring, imported=imported, category=category)}


@router.get("/appgen/ideas/{idea_id}")
def appgen_idea_detail(idea_id: str):
    row = appgen_get_idea(idea_id)
    if not row:
        raise HTTPException(status_code=404, detail="appgen idea not found")
    return row


@router.get("/appgen/runs")
def appgen_runs(status: str | None = None, run_type: str | None = None, limit: int = 100):
    return {"items": appgen_list_runs(status=status, run_type=run_type, limit=limit)}


@router.get("/appgen/runs/{run_id}")
def appgen_run_detail(run_id: str):
    row = appgen_get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="appgen run not found")
    return row


@router.get("/appgen/outbox")
def appgen_outbox(limit: int = 200):
    return {"items": appgen_list_outbox(limit=limit)}


@router.post("/appgen/ideas/{idea_id}/export")
def appgen_export(idea_id: str):
    # Reuse existing exporter endpoint behavior via service if available.
    from appgen.services.exporter import export_to_appcreator

    try:
        out = export_to_appcreator(idea_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return out
