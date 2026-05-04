from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.paths import dashburg_data_dir
from app.db.session import get_session
from app.models.ideavault import IdeaVaultItem
from app.modules.appgen.opportunity import dedupe_opportunities, normalize_opportunity
from app.services.opportunity_lineage import record_lineage
from app.modules.topic_proxy.schemas import AutoRunRequest, PromoteIdeaRequest, StartRunRequest, TargetedRunRequest
from app.modules.topic_proxy.service import TopicProxyError, TopicProxyService, get_topic_proxy_service

router = APIRouter(prefix="/api/topic", tags=["topic"])
_SEARCH_STRATEGY_PATH = dashburg_data_dir() / "topic_search_strategy.json"
_DEFAULT_SEARCH_STRATEGY: dict[str, Any] = {
    "default_subreddits": [
        "smallbusiness",
        "Entrepreneur",
        "startups",
        "marketing",
        "sales",
        "ecommerce",
        "shopify",
        "agency",
        "freelance",
        "content_marketing",
        "youtube",
        "creators",
        "webdev",
        "programming",
        "gamedev",
        "Unity3D",
        "indiegames",
        "sysadmin",
        "operations"
    ],
    "default_search_terms": [
        "manual process",
        "spreadsheet tracking",
        "repetitive task",
        "copy paste work",
        "approval bottleneck",
        "status update chaos",
        "content workflow bottleneck",
        "lead follow up gaps",
        "creator production pipeline pain",
        "field service scheduling pain",
        "shopify operations pain",
        "dev tooling friction",
        "game dev workflow pain",
    ],
    "pain_queries": [
        "manual process",
        "spreadsheet tracking",
        "repetitive task",
        "copy paste work",
    ],
    "custom_sites": [],
    "web_provider_chain": ["ddg", "dataforseo"],
    "methods": ["reddit_search", "reddit_comments", "web_search"],
}


def _clamp_int(value: Any, *, lo: int, hi: int, default: int) -> tuple[int, bool]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    clamped = max(lo, min(hi, parsed))
    return clamped, clamped != parsed


def _merge_metadata(upstream: Any, metadata: dict[str, Any]) -> Any:
    if isinstance(upstream, dict):
        return {**upstream, "_dashburg": metadata}
    return {"data": upstream, "_dashburg": metadata}


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_run_payload(payload: Any) -> Any:
    root = _as_record(payload)
    if not root:
        return payload

    progress = _as_record(root.get("progress"))
    if not progress:
        progress = _as_record(_as_record(root.get("job")).get("progress"))
    summary = _as_record(root.get("summary"))
    counts = _as_record(root.get("counts")) or _as_record(_as_record(root.get("job")).get("counts"))

    status_value = _first_non_empty_str(root.get("status"), _as_record(root.get("job")).get("status")).lower()
    stage = _first_non_empty_str(root.get("stage"), root.get("current_stage"), progress.get("stage"), summary.get("stage"))
    if not stage and status_value == "running":
        stage = "processing"
    progress_raw = root.get("progress_pct", root.get("progress_percent", progress.get("percent", summary.get("progress_pct"))))
    try:
        progress_pct = float(progress_raw) if progress_raw is not None else None
    except (TypeError, ValueError):
        progress_pct = None
    if progress_pct is None and status_value == "running":
        progress_pct = 1.0
    if progress_pct is not None:
        progress_pct = max(0.0, min(100.0, progress_pct))

    heartbeat_at = _first_non_empty_str(
        root.get("heartbeat_at"),
        root.get("updated_at"),
        _as_record(root.get("job")).get("updated_at"),
        root.get("started_at"),
        root.get("created_at"),
        _as_record(root.get("job")).get("started_at"),
        _as_record(root.get("job")).get("created_at"),
        summary.get("heartbeat_at"),
    )

    normalized = dict(root)
    if stage:
        normalized["stage"] = stage
    if progress_pct is not None:
        normalized["progress_pct"] = progress_pct
    if heartbeat_at:
        normalized["heartbeat_at"] = heartbeat_at
    if counts:
        normalized["counts"] = counts
    return normalized


def _status_report_from_events(payload: Any, events_payload: Any) -> dict[str, Any]:
    root = _as_record(payload)
    events_obj = _as_record(events_payload)
    raw_items = events_obj.get("items")
    if not isinstance(raw_items, list):
        raw_items = events_obj.get("events")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []

    done = 0
    failed = 0
    running = 0
    for item in items:
        status = str(item.get("status", "")).strip().lower()
        if status in {"ok", "completed", "success"}:
            done += 1
        elif status in {"error", "failed"}:
            failed += 1
        elif status in {"running", "queued"}:
            running += 1

    now = datetime.now(timezone.utc)
    started_at = _parse_iso_dt(_first_non_empty_str(root.get("started_at"), _as_record(root.get("job")).get("started_at")))
    heartbeat_at = _parse_iso_dt(_first_non_empty_str(root.get("heartbeat_at"), root.get("updated_at"), _as_record(root.get("job")).get("updated_at")))
    progress_raw = root.get("progress_pct")
    try:
        progress_pct = float(progress_raw) if progress_raw is not None else None
    except (TypeError, ValueError):
        progress_pct = None

    eta_seconds: int | None = None
    if started_at and progress_pct and progress_pct > 0 and progress_pct < 100:
        elapsed = (now - started_at).total_seconds()
        if elapsed > 0:
            eta_seconds = int((elapsed * (100.0 - progress_pct)) / progress_pct)

    heartbeat_age_seconds: int | None = None
    if heartbeat_at is not None:
        heartbeat_age_seconds = max(0, int((now - heartbeat_at).total_seconds()))

    last_event_at: datetime | None = None
    for item in items:
        ts = _parse_iso_dt(_first_non_empty_str(item.get("created_at")))
        if ts is None:
            continue
        if last_event_at is None or ts > last_event_at:
            last_event_at = ts
    stage_stalled_seconds: int | None = None
    if last_event_at is not None:
        stage_stalled_seconds = max(0, int((now - last_event_at).total_seconds()))

    status_value = str(root.get("status", "")).strip().lower()
    blocked_reason = None
    if status_value == "running":
        if stage_stalled_seconds is not None and stage_stalled_seconds > 180:
            blocked_reason = "no_stage_events_recently"
        elif len(items) == 0 and started_at is not None and (now - started_at).total_seconds() > 30:
            blocked_reason = "waiting_for_first_stage_event"
            if stage_stalled_seconds is None:
                stage_stalled_seconds = max(0, int((now - started_at).total_seconds()))

    return {
        "events_total": len(items),
        "events_done": done,
        "events_failed": failed,
        "events_running": running,
        "eta_seconds": eta_seconds,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stage_stalled_seconds": stage_stalled_seconds,
        "blocked_reason": blocked_reason,
    }


def _normalize_ingest_overrides(
    ingest_overrides: dict[str, Any] | None,
    *,
    max_posts_per_source: int | None = None,
    max_comment_posts: int | None = None,
    max_comments_per_thread: int | None = None,
    concurrency: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = dict(ingest_overrides or {})
    overrides: dict[str, Any] = {}
    clamped: dict[str, Any] = {}

    # Topic expects ingest_overrides to be int-like values only.
    for key, value in raw.items():
        try:
            parsed = int(value)
            overrides[key] = parsed
        except (TypeError, ValueError):
            continue

    if max_posts_per_source is not None:
        v, changed = _clamp_int(max_posts_per_source, lo=1, hi=100, default=15)
        overrides["max_posts_per_source"] = v
        overrides["reddit_max_posts"] = v
        if changed:
            clamped["max_posts_per_source"] = v

    if max_comment_posts is not None:
        v, changed = _clamp_int(max_comment_posts, lo=1, hi=50, default=10)
        overrides["reddit_max_comment_posts"] = v
        if changed:
            clamped["max_comment_posts"] = v

    if max_comments_per_thread is not None:
        v, changed = _clamp_int(max_comments_per_thread, lo=1, hi=200, default=50)
        overrides["max_comments_per_thread"] = v
        overrides["reddit_max_comments_per_post"] = v
        if changed:
            clamped["max_comments_per_thread"] = v

    if concurrency is not None:
        v, changed = _clamp_int(concurrency, lo=1, hi=4, default=2)
        overrides["concurrency"] = v
        if changed:
            clamped["concurrency"] = v
    return overrides, clamped


def _load_local_search_strategy() -> dict[str, Any]:
    if not _SEARCH_STRATEGY_PATH.exists():
        _SEARCH_STRATEGY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SEARCH_STRATEGY_PATH.write_text(json.dumps(_DEFAULT_SEARCH_STRATEGY, indent=2), encoding="utf-8")
        return dict(_DEFAULT_SEARCH_STRATEGY)
    try:
        payload = json.loads(_SEARCH_STRATEGY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    merged = dict(_DEFAULT_SEARCH_STRATEGY)
    for key, default in _DEFAULT_SEARCH_STRATEGY.items():
        value = payload.get(key, default)
        if isinstance(default, list):
            merged[key] = [str(item).strip() for item in (value or []) if str(item).strip()]
        else:
            merged[key] = value
    return merged


def _save_local_search_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    current = _load_local_search_strategy()
    merged = dict(current)
    for key in _DEFAULT_SEARCH_STRATEGY:
        value = payload.get(key, current.get(key))
        if isinstance(_DEFAULT_SEARCH_STRATEGY[key], list):
            merged[key] = [str(item).strip() for item in (value or []) if str(item).strip()]
        else:
            merged[key] = value
    _SEARCH_STRATEGY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SEARCH_STRATEGY_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def _raise_proxy_error(exc: TopicProxyError) -> None:
    status_code = exc.upstream_status or 502
    if status_code < 100:
        status_code = 502
    raise HTTPException(
        status_code=status_code,
        detail={
            "message": exc.message,
            "upstream_status": exc.upstream_status,
            "upstream_body": exc.upstream_body,
        },
    )


async def _request_any_path(
    service: TopicProxyService,
    method: str,
    candidates: list[str],
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    use_cache: bool = False,
) -> Any:
    last_error: TopicProxyError | None = None
    for path in candidates:
        try:
            return await service.request(method, path, params=params, json_body=json_body, use_cache=use_cache)
        except TopicProxyError as exc:
            last_error = exc
            if exc.upstream_status != 404:
                raise
    if last_error is not None:
        raise last_error
    raise TopicProxyError("No request candidates configured", upstream_status=500)


@router.get("/health")
async def topic_health(service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/health", use_cache=True)
    except TopicProxyError as exc:
        if exc.upstream_status == 404:
            return {"ok": True, "deleted": False, "reason": "not_found"}
        _raise_proxy_error(exc)


@router.get("/trending")
async def topic_trending(
    limit: int = Query(default=20, ge=1, le=200),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/topics/trending", params={"limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/runs")
async def topic_runs(
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        upstream = await service.request("GET", "/runs", params={"limit": limit}, use_cache=True)
        obj = _as_record(upstream)
        for key in ("runs", "items", "jobs"):
            rows = obj.get(key)
            if isinstance(rows, list):
                obj[key] = [_normalize_run_payload(row) for row in rows]
        return obj if obj else upstream
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/runs/latest")
async def topic_runs_latest(service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/runs/latest", use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/search_strategy")
async def topic_search_strategy(service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/search_strategy", use_cache=False)
    except TopicProxyError as exc:
        if exc.upstream_status in {404, 405}:
            return _load_local_search_strategy()
        _raise_proxy_error(exc)


@router.put("/search_strategy")
async def topic_search_strategy_update(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("PUT", "/search_strategy", json_body=payload, use_cache=False)
    except TopicProxyError as exc:
        if exc.upstream_status in {404, 405}:
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="search strategy payload must be an object")
            return _save_local_search_strategy(payload)
        _raise_proxy_error(exc)


@router.post("/runs/start")
async def topic_runs_start(
    payload: StartRunRequest = Body(...),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    limit, _ = _clamp_int(payload.limit, lo=1, hi=1000, default=200)
    body: dict[str, Any] = {
        "query": payload.query,
        "topic": payload.topic,
        "limit": limit,
        "enable_youtube": bool(payload.enable_youtube),
        "target_final_ideas": int(payload.target_final_ideas),
        "enable_pain_graph": bool(payload.enable_pain_graph),
        "ingest_overrides": payload.ingest_overrides or {},
        "use_default_subreddits": bool(payload.use_default_subreddits),
        "use_default_search_terms": bool(payload.use_default_search_terms),
        "enable_reddit": bool(payload.enable_reddit),
        "enable_web_search": bool(payload.enable_web_search),
        "low_fanout_mode": bool(payload.low_fanout_mode),
        "category_mode": payload.category_mode,
        "category_filters": payload.category_filters or [],
        "exclude_categories": payload.exclude_categories or [],
    }
    if payload.subreddits:
        body["subreddits"] = [s.strip() for s in payload.subreddits if str(s).strip()]
    if payload.search_terms:
        body["search_terms"] = [s.strip() for s in payload.search_terms if str(s).strip()]
    try:
        return await service.request("POST", "/runs/start", json_body=body)
    except TopicProxyError as exc:
        if exc.upstream_status in {404, 405}:
            fallback_body = {
                "query": payload.query,
                "topic": payload.topic,
                "limit": min(limit, 100),
                "enable_youtube": bool(payload.enable_youtube),
            }
            return _merge_metadata(
                await service.request("POST", "/runs/targeted", json_body=fallback_body),
                {"fallback": "targeted", "forwarded_body": fallback_body},
            )
        _raise_proxy_error(exc)


@router.get("/runs/{run_id}")
async def topic_run_detail(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        upstream = await service.request("GET", f"/runs/{run_id}", use_cache=False)
        normalized = _normalize_run_payload(upstream)
        try:
            events = await _request_any_path(
                service,
                "GET",
                [f"/runs/{run_id}/events", f"/runs/{run_id}/logs"],
                params={"offset": 0, "max_lines": 200, "limit": 200},
                use_cache=False,
            )
        except TopicProxyError:
            events = {}
        report = _status_report_from_events(normalized, events)
        if isinstance(normalized, dict):
            meta = _as_record(normalized.get("_dashburg"))
            normalized["_dashburg"] = {**meta, "status_report": report}
        return normalized
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.post("/runs/{run_id}/cancel")
async def topic_run_cancel(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await _request_any_path(
            service,
            "POST",
            [f"/runs/{run_id}/cancel", f"/runs/cancel/{run_id}"],
            use_cache=False,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.delete("/runs/{run_id}")
async def topic_run_delete(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await _request_any_path(
            service,
            "DELETE",
            [f"/runs/{run_id}", f"/runs/delete/{run_id}"],
            use_cache=False,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.post("/runs/targeted")
async def topic_run_targeted(
    payload: TargetedRunRequest,
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        limit, clamped_limit = _clamp_int(payload.limit, lo=1, hi=300, default=40)
        target_final_ideas, clamped_target = _clamp_int(payload.target_final_ideas, lo=1, hi=100, default=5)
        comment_posts, clamped_comment_posts = _clamp_int(payload.max_comment_posts, lo=1, hi=50, default=10)
        comments, clamped_comments = _clamp_int(payload.max_comments_per_thread, lo=1, hi=200, default=50)
        ingest_overrides, clamped_overrides = _normalize_ingest_overrides(
            payload.ingest_overrides,
            max_comment_posts=comment_posts,
            max_comments_per_thread=comments,
        )
        enable_youtube = payload.enable_youtube if payload.youtube is None else bool(payload.youtube)
        body = {
            "query": payload.query,
            "topic": payload.topic,
            "limit": limit,
            "enable_youtube": bool(enable_youtube),
            "target_final_ideas": target_final_ideas,
            "enable_pain_graph": True,
            "ingest_overrides": ingest_overrides,
            "recency_window": payload.recency_window,
            "subreddits": [s.strip() for s in (payload.subreddits or []) if str(s).strip()],
            "search_terms": [s.strip() for s in (payload.search_terms or []) if str(s).strip()],
            "use_default_subreddits": bool(payload.use_default_subreddits),
            "use_default_search_terms": bool(payload.use_default_search_terms),
            "enable_reddit": bool(payload.enable_reddit),
            "enable_web_search": bool(payload.enable_web_search),
            "low_fanout_mode": bool(payload.low_fanout_mode),
            "category_mode": payload.category_mode,
            "category_filters": payload.category_filters or [],
            "exclude_categories": payload.exclude_categories or [],
        }
        upstream = await service.request("POST", "/runs/start", json_body=body)
        metadata = {
            "forwarded_body": body,
            "clamped": {
                **({"limit": limit} if clamped_limit else {}),
                **({"target_final_ideas": target_final_ideas} if clamped_target else {}),
                **({"max_comment_posts": comment_posts} if clamped_comment_posts else {}),
                **({"max_comments_per_thread": comments} if clamped_comments else {}),
                **clamped_overrides,
            },
        }
        return _merge_metadata(upstream, metadata)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.post("/runs/auto")
async def topic_run_auto(payload: AutoRunRequest, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        ideas_per_run, c_ideas = _clamp_int(payload.ideas_per_run, lo=1, hi=10, default=5)
        target_topics, c_topics = _clamp_int(payload.target_topics, lo=1, hi=25, default=8)
        limit_per_topic, c_limit = _clamp_int(payload.limit_per_topic, lo=1, hi=100, default=20)
        max_comment_posts, c_comment_posts = _clamp_int(payload.max_comment_posts, lo=1, hi=50, default=10)
        target_final_ideas, c_target_final = _clamp_int(
            payload.target_final_ideas if payload.target_final_ideas is not None else ideas_per_run,
            lo=1,
            hi=100,
            default=ideas_per_run,
        )
        computed_limit = max(1, min(500, target_topics * limit_per_topic))

        ingest_overrides, clamped_overrides = _normalize_ingest_overrides(
            payload.ingest_overrides,
            max_posts_per_source=payload.max_posts_per_source,
            max_comment_posts=max_comment_posts,
            max_comments_per_thread=payload.max_comments_per_thread,
            concurrency=payload.concurrency,
        )
        body = {
            "query": (payload.search_terms[0] if payload.search_terms else "") or "manual process",
            "topic": (payload.subreddits[0] if payload.subreddits else "") or "general",
            "ideas_per_run": ideas_per_run,
            "target_topics": target_topics,
            "limit_per_topic": limit_per_topic,
            "limit": computed_limit,
            "target_final_ideas": target_final_ideas,
            "ingest_overrides": ingest_overrides,
            "subreddits": payload.subreddits,
            "search_terms": payload.search_terms,
            "use_default_subreddits": payload.use_default_subreddits,
            "use_default_search_terms": payload.use_default_search_terms,
            "enable_youtube": bool(payload.enable_youtube),
            "enable_reddit": payload.enable_reddit,
            "enable_web_search": payload.enable_web_search,
            "low_fanout_mode": payload.low_fanout_mode,
            "category_mode": payload.category_mode,
            "category_filters": payload.category_filters or [],
            "exclude_categories": payload.exclude_categories or [],
        }
        upstream = await service.request(
            "POST",
            "/runs/auto",
            json_body=body,
            prefix_order=("api_topic", "raw", "api_v1"),
        )
        metadata = {
            "forwarded_body": body,
            "clamped": {
                **({"ideas_per_run": ideas_per_run} if c_ideas else {}),
                **({"target_topics": target_topics} if c_topics else {}),
                **({"limit_per_topic": limit_per_topic} if c_limit else {}),
                **({"limit": computed_limit} if c_topics or c_limit else {}),
                **({"target_final_ideas": target_final_ideas} if c_target_final else {}),
                **({"max_comment_posts": max_comment_posts} if c_comment_posts else {}),
                **clamped_overrides,
            },
        }
        return _merge_metadata(upstream, metadata)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/ideas")
async def topic_ideas(
    cluster_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request(
            "GET",
            "/ideas",
            params={"cluster_id": cluster_id, "limit": limit},
            use_cache=True,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/ideas/{idea_id}")
async def topic_idea_detail(idea_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/ideas/{idea_id}", use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.post("/ideas/promote")
async def topic_idea_promote(
    payload: PromoteIdeaRequest,
    service: TopicProxyService = Depends(get_topic_proxy_service),
    session: Session = Depends(get_session),
) -> Any:
    upstream: Any = None
    try:
        upstream = await service.request("POST", "/ideas/promote", json_body=payload.model_dump(exclude_none=True))
    except TopicProxyError as exc:
        # Keep backward compatibility: upstream endpoint is optional.
        if exc.upstream_status not in {404, 405, 501}:
            _raise_proxy_error(exc)

    now = datetime.utcnow()
    max_rank = session.exec(select(IdeaVaultItem.priority_rank).order_by(IdeaVaultItem.priority_rank.desc())).first()
    next_rank = int(max_rank) + 1 if max_rank is not None else 0
    title = payload.title.strip() or "Untitled opportunity"
    row = IdeaVaultItem(
        id=uuid.uuid4().hex,
        title=title,
        summary=(payload.summary or "").strip(),
        type="idea",
        status="new",
        tags_json=json.dumps(payload.tags, ensure_ascii=True),
        source_json=json.dumps(
            {
                "module": "IdeaFactory",
                "run_id": payload.run_id,
                "idea_id": payload.idea_id,
                "related_runs": [payload.run_id] if payload.run_id else [],
                "evidence_source": "/api/topic/opportunities",
                "idea_type": _first_non_empty_str(payload.raw_json.get("idea_type"), ""),
                "lineage": {
                    "origin_module": "TopicInsights",
                    "origin_run_id": payload.run_id,
                    "origin_idea_id": payload.idea_id,
                },
                "recommended_output_type": "dbvid"
                if _first_non_empty_str(payload.raw_json.get("idea_type"), "").lower() == "video"
                else "app_or_saas",
            },
            ensure_ascii=True,
        ),
        payload_json=json.dumps(payload.raw_json, ensure_ascii=True),
        score=payload.score,
        pinned=False,
        priority_rank=next_rank,
        created_at=now,
        updated_at=now,
        last_touched_at=now,
    )
    session.add(row)
    session.commit()
    if payload.run_id:
        record_lineage(
            session,
            from_kind="ideafactory_run",
            from_id=payload.run_id,
            to_kind="ideavault_item",
            to_id=row.id,
            relation="promoted",
            context={"idea_id": payload.idea_id, "source": "topic_proxy.promote"},
            score=payload.score,
        )
    if payload.idea_id:
        record_lineage(
            session,
            from_kind=f"opportunity_{_first_non_empty_str(payload.raw_json.get('idea_type'), 'generic').lower()}",
            from_id=payload.idea_id,
            to_kind="ideavault_item",
            to_id=row.id,
            relation="selected",
            context={"run_id": payload.run_id, "source": "topic_proxy.promote"},
            score=payload.score,
        )

    return {
        "ok": True,
        "ideavault_item_id": row.id,
        "upstream": upstream,
    }


@router.get("/signals")
async def topic_signals(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/signals", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/micro_problems")
async def topic_micro_problems(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/micro_problems", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/workarounds")
async def topic_workarounds(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/workarounds", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/pain_graph")
async def topic_pain_graph(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/pain_graph", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/ideas/top")
async def topic_ideas_top(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/ideas/top", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/opportunities")
async def topic_opportunities(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=300),
    include_video: bool = Query(default=True),
    include_ideas: bool = Query(default=True),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    opportunities: list[dict[str, Any]] = []
    if include_ideas:
        try:
            ideas = await service.request("GET", "/ideas/top", params={"run_id": run_id, "limit": limit}, use_cache=True)
            rows = ideas if isinstance(ideas, list) else _as_record(ideas).get("items", [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        opportunities.append(normalize_opportunity(row, source_run_id=run_id))
        except TopicProxyError as exc:
            if exc.upstream_status not in {404, 405}:
                _raise_proxy_error(exc)
    if include_video:
        try:
            vids = await _request_any_path(
                service,
                "GET",
                ["/video_ideas/top", "/ideas/top"],
                params={"run_id": run_id, "limit": limit},
                use_cache=True,
            )
            rows = vids if isinstance(vids, list) else _as_record(vids).get("items", [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        opportunities.append(normalize_opportunity({**row, "idea_type": "video"}, source_run_id=run_id))
        except TopicProxyError as exc:
            if exc.upstream_status not in {404, 405}:
                _raise_proxy_error(exc)
    deduped = dedupe_opportunities(opportunities)[:limit]
    return {
        "items": deduped,
        "count": len(deduped),
        "run_id": run_id,
    }


@router.get("/video_ideas")
async def topic_video_ideas(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await _request_any_path(
            service,
            "GET",
            ["/video_ideas", "/ideas"],
            params={"run_id": run_id, "limit": limit},
            use_cache=True,
        )
    except TopicProxyError as exc:
        # AppGen UUID runs do not always have video-idea endpoints upstream.
        if run_id and exc.upstream_status in {404, 405, 500}:
            return {"items": [], "count": 0, "run_id": run_id}
        _raise_proxy_error(exc)


@router.get("/video_ideas/top")
async def topic_video_ideas_top(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await _request_any_path(
            service,
            "GET",
            ["/video_ideas/top", "/ideas/top"],
            params={"run_id": run_id, "limit": limit},
            use_cache=True,
        )
    except TopicProxyError as exc:
        # AppGen UUID runs do not always have video-idea endpoints upstream.
        if run_id and exc.upstream_status in {404, 405, 500}:
            return {"items": [], "count": 0, "run_id": run_id}
        _raise_proxy_error(exc)


@router.get("/video_ideas/{video_idea_id}")
async def topic_video_idea_detail(video_idea_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await _request_any_path(
            service,
            "GET",
            [f"/video_ideas/{video_idea_id}", f"/ideas/{video_idea_id}"],
            use_cache=True,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/runs/{run_id}/logs")
async def topic_run_logs(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    max_lines: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        upstream = await _request_any_path(
            service,
            "GET",
            [
                f"/runs/{run_id}/logs",
                f"/runs/{run_id}/events",
                f"/appgen/runs/{run_id}/logs",
            ],
            params={"offset": offset, "max_lines": max_lines, "limit": max_lines},
            use_cache=False,
        )
        obj = _as_record(upstream)
        if not obj:
            return upstream
        if isinstance(obj.get("lines"), list):
            return obj
        raw_items = obj.get("items")
        if not isinstance(raw_items, list):
            raw_items = obj.get("events")
        if isinstance(raw_items, list):
            lines: list[str] = []
            for item in raw_items:
                if isinstance(item, str):
                    lines.append(item)
                    continue
                if not isinstance(item, dict):
                    lines.append(str(item))
                    continue
                created = _first_non_empty_str(item.get("created_at"))
                stage = _first_non_empty_str(item.get("stage_name"), item.get("stage"), "event")
                status = _first_non_empty_str(item.get("status"))
                output_count = item.get("output_count")
                input_count = item.get("input_count")
                error = _first_non_empty_str(item.get("error_message"))
                parts = [
                    f"[{created}]" if created else "",
                    stage,
                    status,
                    f"in={input_count}" if input_count is not None else "",
                    f"out={output_count}" if output_count is not None else "",
                    f"error={error}" if error else "",
                ]
                lines.append(" ".join(part for part in parts if part))
            return {
                "lines": lines,
                "items": raw_items,
                "offset": obj.get("offset", offset),
                "next_offset": obj.get("next_offset", obj.get("offset", offset)),
                "has_more": bool(obj.get("has_more", False)),
            }
        return obj
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/logs/tail")
async def topic_logs_tail(
    offset: int = Query(default=0, ge=0),
    max_lines: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request(
            "GET",
            "/logs/tail",
            params={"offset": offset, "max_lines": max_lines},
            use_cache=False,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/pains")
async def topic_pains(
    topic: str | None = Query(default=None),
    cluster_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request(
            "GET",
            "/pains",
            params={"topic": topic, "cluster_id": cluster_id, "limit": limit},
            use_cache=True,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/clusters")
async def topic_clusters(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/clusters", params={"run_id": run_id, "limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/clusters/{cluster_id}")
async def topic_cluster_detail(cluster_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/clusters/{cluster_id}", use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/providers/stats")
async def topic_provider_stats(
    limit: int = Query(default=200, ge=1, le=1000),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/providers/stats", params={"limit": limit}, use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/appgen/ideas")
async def topic_appgen_ideas(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    sort: str = Query(default="updated_desc"),
    needs_scoring: bool | None = Query(default=None),
    imported: bool | None = Query(default=None),
    category: str | None = Query(default=None),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request(
            "GET",
            "/appgen/ideas",
            params={
                "status": status,
                "q": q,
                "run_id": run_id,
                "sort": sort,
                "needs_scoring": needs_scoring,
                "imported": imported,
                "category": category,
            },
            use_cache=True,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/appgen/ideas/{idea_id}")
async def topic_appgen_idea_detail(idea_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/appgen/ideas/{idea_id}", use_cache=True)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/appgen/runs")
async def topic_appgen_runs(
    status: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    try:
        return await service.request(
            "GET",
            "/appgen/runs",
            params={"status": status, "run_type": run_type, "limit": limit},
            use_cache=True,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.get("/appgen/runs/{run_id}")
async def topic_appgen_run_detail(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/appgen/runs/{run_id}", use_cache=True)
    except TopicProxyError as exc:
        if exc.upstream_status == 404:
            return {"id": run_id, "status": "missing", "error_text": "not_found"}
        _raise_proxy_error(exc)


@router.post("/appgen/runs/{run_id}/cancel")
async def topic_appgen_run_cancel(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        return await _request_any_path(
            service,
            "POST",
            [f"/appgen/runs/{run_id}/cancel", f"/appgen/runs/cancel/{run_id}"],
            use_cache=False,
        )
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.delete("/appgen/runs/{run_id}")
async def topic_appgen_run_delete(run_id: str, service: TopicProxyService = Depends(get_topic_proxy_service)) -> Any:
    try:
        try:
            return await _request_any_path(
                service,
                "DELETE",
                [f"/appgen/runs/{run_id}", f"/appgen/runs/delete/{run_id}"],
                use_cache=False,
            )
        except TopicProxyError as exc:
            if exc.upstream_status not in {404, 405}:
                raise
            return await _request_any_path(
                service,
                "POST",
                [f"/appgen/runs/{run_id}/delete", f"/appgen/runs/delete/{run_id}"],
                use_cache=False,
            )
    except TopicProxyError as exc:
        if exc.upstream_status == 404:
            return {"ok": True, "deleted": False, "reason": "not_found", "run_id": run_id}
        _raise_proxy_error(exc)


@router.post("/appgen/analyze-run")
async def topic_appgen_analyze_run(
    payload: dict[str, Any] = Body(...),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    run_id = _first_non_empty_str(payload.get("appgen_run_id"))
    if not run_id:
        raise HTTPException(status_code=400, detail="appgen_run_id is required")
    try:
        return await service.request("POST", "/appgen/analyze-run", json_body={"appgen_run_id": run_id}, use_cache=False)
    except TopicProxyError as exc:
        _raise_proxy_error(exc)


@router.post("/appgen/generate")
async def topic_appgen_generate(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: TopicProxyService = Depends(get_topic_proxy_service),
) -> Any:
    body = {
        "pain_point_ids": payload.get("pain_point_ids") if isinstance(payload.get("pain_point_ids"), list) else [],
        "seed_text": _first_non_empty_str(payload.get("seed_text")),
        "count": max(1, min(10, int(payload.get("count") or 5))),
        "constraints": payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {},
    }
    if not body["seed_text"] and not body["pain_point_ids"]:
        raise HTTPException(status_code=400, detail="seed_text or pain_point_ids is required")
    try:
        return await service.request("POST", "/api/appgen/generate", json_body=body, use_cache=False, prefix_order=("raw",))
    except TopicProxyError as exc:
        _raise_proxy_error(exc)
