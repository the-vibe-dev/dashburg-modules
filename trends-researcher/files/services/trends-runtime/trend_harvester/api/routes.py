from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, delete, desc, func, select
from sqlalchemy.orm import Session

from trend_harvester.config import get_settings
from trend_harvester.db import SessionLocal, get_db
from trend_harvester.enums import RunStatus
from trend_harvester.models import Action, Analysis, Candidate, Run, Topic, TopicInstance
from trend_harvester.schemas import (
    ActionsResponse,
    ConfigValidateResponse,
    ExportRequest,
    ExportResponse,
    GenericStatusResponse,
    OpenAiApiKeyStatus,
    RunLogsResponse,
    RunResponse,
    RunResultsResponse,
    RunStartRequest,
    RunStartResponse,
    TopicActionRequest,
    TopicDetailResponse,
    TopicResult,
)
from trend_harvester.services.openai_key_store import (
    clear_openai_api_key,
    openai_api_key_status,
    set_openai_api_key,
)
from trend_harvester.services.exporter import export_idea_factory_v2, export_topic_factory_v1
from trend_harvester.services.run_logs import append_run_log, delete_run_log, read_run_log
from trend_harvester.services.strategy_pass import run_multiphase_strategy
from trend_harvester.services.channels import get_channel_profiles, get_channel_records_json
from trend_harvester.services.channel_metadata import ChannelMetadataService
from trend_harvester.services.channel_ranking import build_channel_rankings
from trend_harvester.services.focus import channel_profile_similarity, focus_relevance_score
from trend_harvester.services.harvester import harvester_service
from trend_harvester.services.scoring import blend_channel_relevance, score_topic_for_channel

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

STALE_QUEUED_SECONDS = 600
STALE_RUNNING_SECONDS = 7200
TOP_BY_SOURCE_LIMIT = 25
TOP_OVERALL_MAX_PER_SOURCE = 10
CHANNELS = [row["display_name"] for row in get_channel_records_json()]
CHANNEL_RECORDS = get_channel_records_json()
CHANNEL_PROFILES = get_channel_profiles()
TOP_PER_CHANNEL_LIMIT = 5
STRATEGY_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="strategy-pass")
_strategy_futures: dict[str, Future] = {}
BUSINESS_SIGNAL_TERMS = (
    "openai",
    "anthropic",
    "oracle",
    "nintendo",
    "tariff",
    "prediction market",
    "data center",
    "api",
    "developer",
    "automation",
    "workflow",
    "compliance",
    "security",
    "saas",
)


def _normalize_channel_map(raw: dict | None) -> dict[str, float]:
    base = {channel: 0.0 for channel in CHANNELS}
    if not isinstance(raw, dict):
        return base
    for channel in CHANNELS:
        value = raw.get(channel, 0.0)
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        base[channel] = max(0.0, min(1.0, score))
    return base


def _published_at_for_topic(db: Session, run_id: str) -> dict[str, datetime | None]:
    rows = db.execute(
        select(TopicInstance.topic_id, Candidate.published_at)
        .join(Candidate, Candidate.url == TopicInstance.url)
        .where(TopicInstance.run_id == run_id, Candidate.run_id == run_id)
        .order_by(Candidate.published_at.desc())
    ).all()
    out: dict[str, datetime | None] = {}
    for row in rows:
        if row.topic_id not in out:
            out[row.topic_id] = row.published_at
    return out


def _action_penalty(action: str | None, settings) -> float:
    if action == "blacklist":
        return settings.novelty_blacklist_penalty
    if action == "used":
        return settings.novelty_used_penalty
    if action == "skip":
        return settings.novelty_skip_penalty
    return 0.0


def _business_signal_boost(title: str) -> float:
    lowered = str(title or "").lower()
    hits = sum(1 for term in BUSINESS_SIGNAL_TERMS if term in lowered)
    if hits <= 0:
        return 0.0
    return min(12.0, float(hits) * 2.25)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _reconcile_run_status(db: Session, run: Run) -> Run:
    if run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        return run
    if harvester_service.is_running(run.id):
        return run

    now = datetime.now(timezone.utc)
    created_at = _as_utc(run.created_at)
    started_at = _as_utc(run.started_at)
    queued_age = (now - created_at).total_seconds() if created_at else 0
    running_age = (now - started_at).total_seconds() if started_at else 0

    is_stale_queued = run.status == RunStatus.QUEUED.value and queued_age >= STALE_QUEUED_SECONDS
    is_stale_running = run.status == RunStatus.RUNNING.value and running_age >= STALE_RUNNING_SECONDS
    if not (is_stale_queued or is_stale_running):
        return run

    run.status = RunStatus.FAILED.value
    run.error = (
        "Run was marked stale by API reconciliation: no active worker task was found for this run."
    )
    run.finished_at = now
    db.commit()
    db.refresh(run)
    return run


def _start_multiphase_pass_if_needed(run: Run, top_topic_ids: list[str], run_totals: dict) -> dict:
    strategy_state = run_totals.get("strategy_v2")
    if not isinstance(strategy_state, dict):
        strategy_state = {}

    status = str(strategy_state.get("status", "idle")).lower()
    if status in {"succeeded", "failed"}:
        return strategy_state
    if run.status != RunStatus.SUCCEEDED.value:
        return strategy_state
    if not top_topic_ids:
        return strategy_state

    future = _strategy_futures.get(run.id)
    if future is not None and not future.done():
        state = dict(strategy_state) if isinstance(strategy_state, dict) else {}
        state["status"] = "running"
        return state
    if status in {"running", "queued"}:
        # Recover from process restarts: persisted queued/running state may exist
        # while in-memory future tracking has been lost.
        strategy_state["status"] = "queued"

    queued_at = datetime.now(timezone.utc).isoformat()
    strategy_state = {
        **strategy_state,
        "status": "queued",
        "queued_at": strategy_state.get("queued_at") or queued_at,
        "resumed_at": queued_at,
    }
    run_totals["strategy_v2"] = strategy_state

    db = SessionLocal()
    try:
        persisted_run = db.get(Run, run.id)
        if persisted_run:
            totals = dict(persisted_run.totals_json) if isinstance(persisted_run.totals_json, dict) else {}
            totals["strategy_v2"] = strategy_state
            persisted_run.totals_json = totals
            db.commit()
    finally:
        db.close()

    run_params = run.params_json if isinstance(run.params_json, dict) else {}
    require_openai = bool(run_params.get("use_openai_strategy", True))
    future = STRATEGY_EXECUTOR.submit(_run_multiphase_pass, run.id, top_topic_ids, require_openai)
    _strategy_futures[run.id] = future

    def _cleanup(_: Future) -> None:
        _strategy_futures.pop(run.id, None)

    future.add_done_callback(_cleanup)
    return strategy_state


def _run_multiphase_pass(run_id: str, top_topic_ids: list[str], require_openai: bool) -> None:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if not run:
            return
        totals = dict(run.totals_json) if isinstance(run.totals_json, dict) else {}
        totals["strategy_v2"] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "current_phase": "phase1",
            "phases": {
                "phase1": {"status": "pending"},
                "phase2": {"status": "pending"},
                "phase3": {"status": "pending"},
                "phase4": {"status": "pending"},
            },
        }
        run.totals_json = totals
        db.commit()
        append_run_log(run_id, "Strategy pass started", event="strategy_started", payload={"status": "running"})

        seed = export_idea_factory_v2(db, top_topic_ids, run_id=run_id)
        seed["top_topic_ids"] = list(top_topic_ids)

        def _phase_progress(event: dict) -> None:
            append_run_log(
                run_id,
                "Strategy progress event",
                event="strategy_progress",
                payload={k: v for k, v in event.items() if k in {"phase", "status", "event", "provider", "error"}},
            )
            session = SessionLocal()
            try:
                current_run = session.get(Run, run_id)
                if not current_run:
                    return
                current_totals = dict(current_run.totals_json) if isinstance(current_run.totals_json, dict) else {}
                state = current_totals.get("strategy_v2", {})
                if not isinstance(state, dict):
                    state = {}
                phase = str(event.get("phase", "")).strip()
                status = str(event.get("status", "")).strip()
                event_name = str(event.get("event", "")).strip()
                phases = state.get("phases", {})
                if not isinstance(phases, dict):
                    phases = {}
                phase_row = phases.get(phase, {})
                if not isinstance(phase_row, dict):
                    phase_row = {}
                phase_row["status"] = status or phase_row.get("status", "running")
                phase_row["updated_at"] = datetime.now(timezone.utc).isoformat()
                if status == "running" and "started_at" not in phase_row:
                    phase_row["started_at"] = phase_row["updated_at"]
                if status in {"ok", "failed"}:
                    phase_row["finished_at"] = phase_row["updated_at"]
                if event.get("error"):
                    phase_row["error"] = str(event.get("error"))[:320]
                    state["last_error"] = str(event.get("error"))[:320]
                if event_name:
                    strategy_events = state.get("events")
                    if not isinstance(strategy_events, list):
                        strategy_events = []
                    strategy_events.append(
                        {
                            "ts": phase_row["updated_at"],
                            "phase": phase or state.get("current_phase", "phase1"),
                            "event": event_name,
                            "provider": str(event.get("provider", "")).strip(),
                            "status": status or phase_row.get("status", ""),
                        }
                    )
                    if len(strategy_events) > 120:
                        strategy_events = strategy_events[-120:]
                    state["events"] = strategy_events
                phases[phase] = phase_row
                state["phases"] = phases
                state["current_phase"] = phase or state.get("current_phase", "phase1")
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                current_totals["strategy_v2"] = state
                current_run.totals_json = current_totals
                session.commit()
            finally:
                session.close()

        artifact = asyncio.run(run_multiphase_strategy(seed, require_openai=require_openai, progress_cb=_phase_progress))

        run = db.get(Run, run_id)
        if not run:
            return
        totals = dict(run.totals_json) if isinstance(run.totals_json, dict) else {}
        totals["strategy_v2"] = {
            "status": "succeeded",
            "started_at": totals.get("strategy_v2", {}).get("started_at"),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "current_phase": "phase4",
            "phases": {
                "phase1": {"status": "ok"},
                "phase2": {"status": "ok"},
                "phase3": {"status": "ok"},
                "phase4": {"status": "ok"},
            },
            "artifact": artifact,
        }
        run.totals_json = totals
        db.commit()
        append_run_log(run_id, "Strategy pass completed", event="strategy_completed", payload={"status": "succeeded"})
    except Exception as exc:  # noqa: BLE001
        run = db.get(Run, run_id)
        if run:
            totals = dict(run.totals_json) if isinstance(run.totals_json, dict) else {}
            totals["strategy_v2"] = {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc)[:500],
            }
            run.totals_json = totals
            db.commit()
        append_run_log(run_id, f"Strategy pass failed: {str(exc)[:320]}", level="ERROR", event="strategy_failed")
    finally:
        db.close()


@router.post("/runs/start", response_model=RunStartResponse)
def start_run(payload: RunStartRequest, db: Session = Depends(get_db)):
    if bool(payload.use_openai_strategy) and not openai_api_key_status().get("configured"):
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is required when use_openai_strategy=true")
    run_id = harvester_service.start_run(db, payload)
    append_run_log(
        run_id,
        "Run accepted by API",
        event="api_start_run",
        payload={"use_openai_strategy": bool(payload.use_openai_strategy), "focus_query": bool((payload.focus_query or "").strip())},
    )
    return RunStartResponse(run_id=run_id)


@router.get("/runs", response_model=list[RunResponse])
def list_runs(db: Session = Depends(get_db)):
    status_priority = case(
        (Run.status == RunStatus.QUEUED.value, 0),
        (Run.status == RunStatus.RUNNING.value, 1),
        else_=2,
    )
    runs = db.scalars(select(Run).order_by(status_priority.asc(), desc(Run.created_at)).limit(200)).all()
    reconciled = [_reconcile_run_status(db, run) for run in runs]
    return [
        RunResponse(
            id=r.id,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            params_json=r.params_json,
            totals_json=r.totals_json,
            error=r.error,
        )
        for r in reconciled
    ]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run = _reconcile_run_status(db, run)
    return RunResponse(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        params_json=run.params_json,
        totals_json=run.totals_json,
        error=run.error,
    )


@router.delete("/runs/{run_id}", response_model=GenericStatusResponse)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run = _reconcile_run_status(db, run)
    if run.status == RunStatus.RUNNING.value and harvester_service.is_running(run.id):
        raise HTTPException(status_code=409, detail="cannot delete a running run")
    if run.status not in {RunStatus.QUEUED.value, RunStatus.FAILED.value, RunStatus.SUCCEEDED.value}:
        raise HTTPException(status_code=400, detail=f"cannot delete run with status {run.status}")

    db.execute(delete(Analysis).where(Analysis.run_id == run_id))
    db.execute(delete(TopicInstance).where(TopicInstance.run_id == run_id))
    db.execute(delete(Candidate).where(Candidate.run_id == run_id))
    db.delete(run)
    db.commit()
    delete_run_log(run_id)
    return GenericStatusResponse(status="ok")


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run = _reconcile_run_status(db, run)
    if run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        raise HTTPException(status_code=400, detail=f"cannot cancel run with status {run.status}")
    harvester_service.request_cancel(run.id)
    run.status = RunStatus.FAILED.value
    run.error = "Run stopped by user."
    run.finished_at = datetime.now(timezone.utc)
    totals = run.totals_json if isinstance(run.totals_json, dict) else {}
    totals["stage"] = "stopped"
    totals["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
    totals["events"] = [*(totals.get("events") if isinstance(totals.get("events"), list) else []), "Run stopped by user."]
    run.totals_json = totals
    db.commit()
    db.refresh(run)
    append_run_log(run.id, "Run canceled by user", event="api_cancel_run", payload={"status": run.status})
    return RunResponse(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        params_json=run.params_json,
        totals_json=run.totals_json,
        error=run.error,
    )


@router.post("/runs/{run_id}/nudge", response_model=RunResponse)
def nudge_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run = _reconcile_run_status(db, run)
    if run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        raise HTTPException(status_code=400, detail=f"cannot nudge run with status {run.status}")

    if not harvester_service.is_running(run.id):
        run.status = RunStatus.QUEUED.value
        totals = run.totals_json if isinstance(run.totals_json, dict) else {}
        totals["stage"] = "nudged"
        totals["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        totals["events"] = [*(totals.get("events") if isinstance(totals.get("events"), list) else []), "Run nudged and rescheduled."]
        run.totals_json = totals
        db.commit()
        harvester_service.nudge_run(run.id)
        db.refresh(run)
        append_run_log(run.id, "Run nudged and re-queued", event="api_nudge_run", payload={"status": run.status})

    return RunResponse(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        params_json=run.params_json,
        totals_json=run.totals_json,
        error=run.error,
    )


@router.get("/runs/{run_id}/logs", response_model=RunLogsResponse)
def get_run_logs(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return RunLogsResponse(**read_run_log(run_id, limit=limit, offset=offset))


@router.get("/runs/{run_id}/results", response_model=RunResultsResponse)
def get_run_results(
    run_id: str,
    limit: int = Query(25, ge=1, le=100),
    include_ranking_debug: bool = Query(False),
    db: Session = Depends(get_db),
):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run = _reconcile_run_status(db, run)
    run_params = run.params_json if isinstance(run.params_json, dict) else {}
    run_totals = run.totals_json if isinstance(run.totals_json, dict) else {}
    focus_query = str(run_params.get("focus_query") or run_totals.get("focus_query") or "").strip()
    min_focus_relevance = run_params.get("min_focus_relevance", run_totals.get("min_focus_relevance", 0.0))
    try:
        min_focus_relevance = max(0.0, min(1.0, float(min_focus_relevance)))
    except (TypeError, ValueError):
        min_focus_relevance = 0.0
    focus_grades_raw = run_totals.get("focus_grades", {})
    focus_grades = focus_grades_raw if isinstance(focus_grades_raw, dict) else {}

    topic_rows = db.execute(
        select(
            Topic.id,
            Topic.canonical_title,
            func.sum(TopicInstance.score).label("total_score"),
            func.count(func.distinct(TopicInstance.source)).label("source_count"),
        )
        .join(TopicInstance, Topic.id == TopicInstance.topic_id)
        .where(TopicInstance.run_id == run_id)
        .group_by(Topic.id)
        .order_by(desc("total_score"))
    ).all()

    analyses = {
        row.topic_id: row
        for row in db.execute(
            select(Analysis.topic_id, Analysis.llm_summary, Analysis.channel_tags_json, Analysis.angle_suggestions_json)
            .where(Analysis.run_id == run_id)
        ).all()
    }

    sources_by_topic = {}
    for row in db.execute(select(TopicInstance.topic_id, TopicInstance.source).where(TopicInstance.run_id == run_id)).all():
        sources_by_topic.setdefault(row.topic_id, set()).add(row.source)
    source_scores_by_topic: dict[str, dict[str, float]] = {}
    for row in db.execute(
        select(TopicInstance.topic_id, TopicInstance.source, func.sum(TopicInstance.score).label("total_source_score"))
        .where(TopicInstance.run_id == run_id)
        .group_by(TopicInstance.topic_id, TopicInstance.source)
    ).all():
        source_scores_by_topic.setdefault(row.topic_id, {})[row.source] = float(row.total_source_score or 0.0)
    topic_ids = [row.id for row in topic_rows]
    historical_run_counts = {
        row.topic_id: int(row.run_count or 0)
        for row in db.execute(
            select(TopicInstance.topic_id, func.count(func.distinct(TopicInstance.run_id)).label("run_count"))
            .where(TopicInstance.topic_id.in_(topic_ids), TopicInstance.run_id != run_id)
            .group_by(TopicInstance.topic_id)
        ).all()
    }
    latest_actions: dict[str, str] = {}
    for topic_id in topic_ids:
        action_row = db.scalar(
            select(Action).where(Action.topic_id == topic_id).order_by(desc(Action.created_at)).limit(1)
        )
        if action_row:
            latest_actions[topic_id] = action_row.action
    published_at_by_topic = _published_at_for_topic(db, run_id)
    settings = get_settings()
    channel_metadata_service = ChannelMetadataService(settings)
    channel_metadata_map = channel_metadata_service.get_cached_metadata_map(db)
    channel_inventory = []
    for row in CHANNEL_RECORDS:
        metadata = channel_metadata_map.get(row["slug"], {})
        channel_inventory.append({**row, **{k: v for k, v in metadata.items() if k not in {"display_name"}}})

    items: list[TopicResult] = []
    for row in topic_rows:
        analysis = analyses.get(row.id)
        llm_channels = _normalize_channel_map(analysis.channel_tags_json if analysis else {})
        grade = focus_grades.get(row.id, {})
        if not isinstance(grade, dict):
            grade = {}
        fit = grade.get("channel_fit", {})
        fit = fit if isinstance(fit, dict) else {}
        try:
            focus_rel = float(grade.get("focus_relevance", 0.0))
        except (TypeError, ValueError):
            focus_rel = 0.0
        if focus_query and focus_rel <= 0.0:
            focus_rel = focus_relevance_score(row.canonical_title, focus_query)
        actionability = 0.0
        try:
            actionability = (
                float(grade.get("actionability_video", 0.0))
                + float(grade.get("actionability_blog", 0.0))
                + float(grade.get("actionability_app", 0.0))
            ) / 3
        except (TypeError, ValueError):
            actionability = 0.0

        base_score = round(float(row.total_score or 0), 2)
        channel_scores: dict[str, float] = {}
        merged_channels: dict[str, float] = {}
        for channel in CHANNELS:
            heuristic = channel_profile_similarity(row.canonical_title, CHANNEL_PROFILES.get(channel, ""))
            model_val = llm_channels.get(channel, 0.0)
            try:
                focus_fit = float(fit.get(channel, 0.0))
            except (TypeError, ValueError):
                focus_fit = 0.0
            merged_model = max(model_val, focus_fit)
            merged_relevance, relevance_reasons = blend_channel_relevance(merged_model, heuristic, focus_rel)
            final_score, ranking_reasons = score_topic_for_channel(
                base_score=base_score,
                channel_relevance=merged_relevance,
                source_count=int(row.source_count or 0),
                historical_runs=historical_run_counts.get(row.id, 0),
                action_penalty=_action_penalty(latest_actions.get(row.id), settings),
                focus_relevance=focus_rel,
                overall_actionability=actionability,
                published_at=published_at_by_topic.get(row.id),
            )
            merged_channels[channel] = merged_relevance
            channel_scores[channel] = final_score

        channel_rankings, filtered_channels, filtered_channel_reasons, ranking_debug = build_channel_rankings(
            topic_id=row.id,
            title=row.canonical_title,
            summary=analysis.llm_summary if analysis else "",
            channels=channel_inventory,
            model_scores=llm_channels,
            focus_fit_scores=fit,
            legacy_relevance=merged_channels,
            channel_scores=channel_scores,
            include_debug=include_ranking_debug or settings.channel_ranking_debug_default,
            settings=settings,
        )

        overall_score = max(channel_scores.values(), default=base_score)
        overall_score += _business_signal_boost(row.canonical_title)
        if focus_query:
            overall_score += focus_rel * 12.0
        items.append(
            TopicResult(
                topic_id=row.id,
                title=row.canonical_title,
                score=round(overall_score, 2),
                sources=sorted(sources_by_topic.get(row.id, set())),
                summary=analysis.llm_summary if analysis else "",
                hooks=analysis.angle_suggestions_json if analysis else [],
                channels=filtered_channels,
                channel_scores=channel_scores,
                channel_reasons=filtered_channel_reasons,
                channel_rankings=channel_rankings,
                ranking_debug=ranking_debug if include_ranking_debug or settings.channel_ranking_debug_default else {},
            )
        )

    items = sorted(items, key=lambda item: (item.score, max(item.channels.values(), default=0.0)), reverse=True)

    if focus_query and min_focus_relevance > 0 and items:
        strong: list[TopicResult] = []
        weak: list[TopicResult] = []
        for item in items:
            grade = focus_grades.get(item.topic_id, {})
            score = None
            if isinstance(grade, dict):
                try:
                    score = float(grade.get("focus_relevance", 0.0))
                except (TypeError, ValueError):
                    score = None
            if score is None or score <= 0.0:
                score = focus_relevance_score(item.title, focus_query)
            if score >= min_focus_relevance:
                strong.append(item)
            else:
                weak.append(item)
        if strong:
            items = strong + weak

    top_by_source: dict[str, list[TopicResult]] = {}
    for source in ["youtube", "reddit", "trends", "x"]:
        source_items = [item for item in items if source in item.sources]
        top_by_source[source] = source_items[:TOP_BY_SOURCE_LIMIT]

    # Balanced overall ranking: prevent a single source from consuming all top slots.
    source_counts = {"youtube": 0, "reddit": 0, "trends": 0, "x": 0}
    selected_ids: set[str] = set()
    top_overall: list[TopicResult] = []

    for item in items:
        if len(top_overall) >= limit:
            break
        source_scores = source_scores_by_topic.get(item.topic_id, {})
        primary_source = max(source_scores, key=source_scores.get, default=(item.sources[0] if item.sources else "unknown"))
        if primary_source in source_counts and source_counts[primary_source] >= TOP_OVERALL_MAX_PER_SOURCE:
            continue
        if item.topic_id in selected_ids:
            continue
        top_overall.append(item)
        selected_ids.add(item.topic_id)
        if primary_source in source_counts:
            source_counts[primary_source] += 1

    if len(top_overall) < limit:
        for item in items:
            if len(top_overall) >= limit:
                break
            if item.topic_id in selected_ids:
                continue
            top_overall.append(item)
            selected_ids.add(item.topic_id)
    top_per_channel: dict[str, list[TopicResult]] = {channel: [] for channel in CHANNELS}
    channel_fit_counts: dict[str, int] = {channel: 0 for channel in CHANNELS}
    channel_candidates: dict[str, list[tuple[float, float, float, TopicResult]]] = {channel: [] for channel in CHANNELS}
    for item in items:
        for ranking in item.channel_rankings:
            channel = str(ranking.get("channel", ""))
            if channel not in channel_candidates:
                continue
            confidence = float(ranking.get("relevance_pct", 0) or 0) / 100.0
            channel_score = float(item.channel_scores.get(channel, 0.0))
            channel_candidates[channel].append((channel_score, confidence, item.score, item))
            channel_fit_counts[channel] += 1

    for channel, candidates in channel_candidates.items():
        sorted_candidates = sorted(candidates, key=lambda tup: (tup[0], tup[1], tup[2]), reverse=True)
        top_per_channel[channel] = [item for _channel_score, _confidence, _score, item in sorted_candidates[:TOP_PER_CHANNEL_LIMIT]]

    channels_used = run_totals.get("channel_inventory", channel_inventory)
    channels_used = channels_used if isinstance(channels_used, list) else channel_inventory
    metadata_by_slug = {row["channel_slug"]: row for row in channel_inventory}
    metadata_by_name = {row["display_name"]: row for row in channel_inventory}
    enriched_channels_used: list[dict] = []
    for row in channels_used:
        if not isinstance(row, dict):
            continue
        metadata = metadata_by_slug.get(str(row.get("slug", "")).strip()) or metadata_by_name.get(str(row.get("display_name", "")).strip()) or {}
        enriched_channels_used.append({**row, **{k: v for k, v in metadata.items() if k not in {"display_name"}}})
    empty_channels = [channel for channel, rows in top_per_channel.items() if not rows]

    logger.debug(
        "run_results_rankings_built run_id=%s topics=%s include_debug=%s",
        run_id,
        len(items),
        include_ranking_debug or settings.channel_ranking_debug_default,
    )

    top_topic_ids = [item.topic_id for item in top_overall]
    idea_bundle = export_idea_factory_v2(db, top_topic_ids, run_id=run.id)
    strategy_state = _start_multiphase_pass_if_needed(run, top_topic_ids, run_totals)
    if isinstance(strategy_state.get("artifact"), dict):
        artifact = strategy_state["artifact"]
        idea_bundle = {
            "ideas": artifact.get("ideas", idea_bundle.get("ideas", [])),
            "ideas_by_type": artifact.get("ideas_by_type", idea_bundle.get("ideas_by_type", {})),
            "idea_groups": artifact.get("idea_groups", idea_bundle.get("idea_groups", [])),
            "big_calls": artifact.get("big_calls", idea_bundle.get("big_calls", [])),
            "score_breakdowns": artifact.get("score_breakdowns", idea_bundle.get("score_breakdowns", {})),
            "evidence_links": artifact.get("evidence_links", idea_bundle.get("evidence_links", {})),
            "recommended_next_actions": artifact.get("recommended_next_actions", idea_bundle.get("recommended_next_actions", [])),
            "review_notes": artifact.get("review_notes", idea_bundle.get("review_notes", [])),
        }
    if not isinstance(idea_bundle.get("ideas_by_type"), dict):
        ideas_by_type = {"video": [], "app": [], "saas": []}
        for idea in idea_bundle.get("ideas", []):
            if not isinstance(idea, dict):
                continue
            idea_type = str(idea.get("idea_type", "")).lower()
            if idea_type in ideas_by_type:
                ideas_by_type[idea_type].append(idea)
        idea_bundle["ideas_by_type"] = ideas_by_type

    return RunResultsResponse(
        run_id=run.id,
        status=run.status,
        top_overall=top_overall,
        top_per_channel=top_per_channel,
        channel_fit_counts=channel_fit_counts,
        top_by_source=top_by_source,
        channels_used=enriched_channels_used,
        empty_channels=empty_channels,
        fetch_plan=run_totals.get("fetch_plan", {}) if isinstance(run_totals.get("fetch_plan", {}), dict) else {},
        idea_candidates=idea_bundle.get("ideas", []),
        idea_candidates_by_type=idea_bundle.get("ideas_by_type", {}),
        idea_groups=idea_bundle.get("idea_groups", []),
        big_calls=idea_bundle.get("big_calls", []),
        score_breakdowns=idea_bundle.get("score_breakdowns", {}),
        evidence_links=idea_bundle.get("evidence_links", {}),
        recommended_next_actions=idea_bundle.get("recommended_next_actions", []),
        review_notes=idea_bundle.get("review_notes", []),
        strategy_status=strategy_state,
    )


@router.get("/topics/{topic_id}", response_model=TopicDetailResponse)
def get_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="topic not found")

    latest_analysis = db.scalar(
        select(Analysis).where(Analysis.topic_id == topic_id).order_by(desc(Analysis.created_at)).limit(1)
    )

    instances = db.scalars(select(TopicInstance).where(TopicInstance.topic_id == topic_id)).all()
    actions = db.scalars(select(Action).where(Action.topic_id == topic_id).order_by(desc(Action.created_at)).limit(20)).all()
    latest_action = actions[0].action if actions else None

    return TopicDetailResponse(
        topic_id=topic.id,
        title=topic.canonical_title,
        summary=latest_analysis.llm_summary if latest_analysis else "",
        hooks=latest_analysis.angle_suggestions_json if latest_analysis else [],
        sources=[
            {
                "source": x.source,
                "url": x.url,
                "score": x.score,
                "reasons": x.reasons_json,
            }
            for x in instances
        ],
        metrics={
            "instance_count": len(instances),
            "total_score": round(sum(x.score for x in instances), 2),
        },
        channel_relevance=_normalize_channel_map(latest_analysis.channel_tags_json if latest_analysis else {}),
        latest_action=latest_action,
        notes=[x.note for x in actions if x.note],
    )


@router.post("/topics/{topic_id}/action", response_model=GenericStatusResponse)
def add_topic_action(topic_id: str, payload: TopicActionRequest, db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="topic not found")
    db.add(Action(topic_id=topic_id, action=payload.action.value, note=payload.note))
    db.commit()
    return GenericStatusResponse(status="ok")


@router.get("/actions", response_model=ActionsResponse)
def list_actions(
    filter: str | None = Query(None),
    since: datetime | None = Query(None),
    db: Session = Depends(get_db),
):
    q = select(Action).order_by(desc(Action.created_at)).limit(500)
    if filter:
        q = q.where(Action.action == filter)
    if since:
        q = q.where(Action.created_at >= since)
    rows = db.scalars(q).all()
    return ActionsResponse(items=[{"id": x.id, "topic_id": x.topic_id, "action": x.action, "note": x.note, "created_at": x.created_at} for x in rows])


@router.post("/export", response_model=ExportResponse)
def export_topics(payload: ExportRequest, db: Session = Depends(get_db)):
    if payload.format == "topic_factory_v1":
        return ExportResponse(**export_topic_factory_v1(db, payload.topic_ids))
    if payload.format in {"idea_factory_v2", "topic_factory_v2"}:
        return ExportResponse(**export_idea_factory_v2(db, payload.topic_ids, run_id=payload.run_id))
    raise HTTPException(status_code=400, detail="unsupported export format")


@router.post("/config/validate", response_model=ConfigValidateResponse)
def validate_config():
    settings = get_settings()
    missing = []
    if not settings.youtube_api_key:
        missing.append("YOUTUBE_API_KEY")
    if not settings.ollama_base_url:
        missing.append("OLLAMA_BASE_URL")
    if not settings.ollama_model:
        missing.append("OLLAMA_MODEL")
    if settings.openai_strategy_enabled and not openai_api_key_status().get("configured"):
        missing.append("OPENAI_API_KEY")
    return ConfigValidateResponse(valid=len(missing) == 0, missing=missing)


@router.get("/openai/key/status", response_model=OpenAiApiKeyStatus)
def openai_key_status() -> dict:
    return openai_api_key_status()


@router.post("/openai/key", response_model=OpenAiApiKeyStatus)
def openai_key_set(payload: dict) -> dict:
    return set_openai_api_key(str(payload.get("api_key", "")))


@router.post("/openai/key/clear", response_model=OpenAiApiKeyStatus)
def openai_key_clear() -> dict:
    return clear_openai_api_key()


@router.get("/health", response_model=GenericStatusResponse)
def health():
    return GenericStatusResponse(status="ok")
