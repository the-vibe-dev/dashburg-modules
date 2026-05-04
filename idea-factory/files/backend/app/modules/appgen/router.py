from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.promoted_idea import PromotedIdea
from app.models.weekly_review import WeeklyReview
from app.modules.appgen.opportunity import (
    classify_idea_type,
    cluster_opportunities,
    compute_week_range,
    dedupe_opportunities,
    normalize_opportunity,
    summarize_themes,
)
from app.modules.topic_proxy.service import TopicProxyError, get_topic_proxy_service
try:
    from app.modules.viralcreator.service import feedback_summary
except Exception:  # pragma: no cover - optional public module dependency
    def feedback_summary(session: Session, days: int = 14) -> dict[str, Any]:
        return {"status": "unavailable", "reason": "viralcreator module not installed"}

from app.schemas.appgen import PromotedIdeaCreate, PromotedIdeaRead, WeeklyReviewRead

router = APIRouter(tags=["appgen"])


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        out = value.strip()
        return out if out else default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _to_dt(value: Any) -> datetime | None:
    raw = _text(value, "")
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _extract_title_summary(raw_json: dict[str, Any], idea_id: str) -> tuple[str, str]:
    title = _text(raw_json.get("title") or raw_json.get("name") or raw_json.get("idea_name") or raw_json.get("app_name") or idea_id, idea_id)
    summary = _text(raw_json.get("summary") or raw_json.get("solution_summary") or raw_json.get("core_problem") or raw_json.get("problem"), "")
    return (title or idea_id, summary)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("items", "results", "data", "rows", "ideas", "video_ideas", "runs"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
    return []


def _to_read_model(row: PromotedIdea) -> PromotedIdeaRead:
    try:
        raw_json = json.loads(row.raw_json or "{}")
        if not isinstance(raw_json, dict):
            raw_json = {}
    except json.JSONDecodeError:
        raw_json = {}
    return PromotedIdeaRead(
        id=row.id or 0,
        source_run_id=row.source_run_id,
        source_idea_id=row.source_idea_id,
        title=row.title,
        summary=row.summary,
        idea_type=row.idea_type or classify_idea_type(raw_json),
        problem_summary=row.problem_summary or _text(raw_json.get("problem_summary") or raw_json.get("problem")),
        target_user=row.target_user or _text(raw_json.get("target_user") or raw_json.get("target")),
        why_now=row.why_now or _text(raw_json.get("why_now")),
        first_build_step=row.first_build_step or _text(raw_json.get("first_build_step") or raw_json.get("mvp_step")),
        raw_json=raw_json,
        created_at=row.created_at,
    )


def _to_weekly_read_model(row: WeeklyReview) -> WeeklyReviewRead:
    try:
        dataset = json.loads(row.dataset_json or "{}")
        if not isinstance(dataset, dict):
            dataset = {}
    except json.JSONDecodeError:
        dataset = {}
    try:
        analysis = json.loads(row.analysis_json or "{}")
        if not isinstance(analysis, dict):
            analysis = {}
    except json.JSONDecodeError:
        analysis = {}
    return WeeklyReviewRead(
        id=row.id,
        week_start=row.week_start,
        week_end=row.week_end,
        status=row.status,
        generated_by=row.generated_by,
        dataset=dataset,
        analysis=analysis,
        analysis_model=row.analysis_model,
        analysis_error=row.analysis_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_weekly_dataset(
    *,
    runs: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    execution_feedback: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    week_start, week_end = compute_week_range(now)
    sorted_opp = sorted(opportunities, key=lambda row: float(row.get("score", 0.0)), reverse=True)
    by_type = {"video": [], "app": [], "saas": []}
    for row in sorted_opp:
        idea_type = _text(row.get("idea_type"), "app")
        by_type.setdefault(idea_type, []).append(row)
    low_confidence = sorted(opportunities, key=lambda row: float(row.get("score", 0.0)))[:8]
    repeated_themes = summarize_themes(opportunities)
    run_ids = [_text(run.get("id") or run.get("run_id"), "") for run in runs]
    run_ids = [rid for rid in run_ids if rid]
    rising_trends = [
        {"topic": _text(row.get("topic") or row.get("title"), ""), "signal_count": row.get("count", 1)}
        for row in repeated_themes[:6]
    ]
    declining_topics = [
        {"topic": _text(row.get("theme"), ""), "reason": "Low opportunity score this week"}
        for row in reversed(repeated_themes[-4:])
    ]
    recommended_next_experiments = []
    for row in sorted_opp[:8]:
        recommended_next_experiments.append(
            {
                "idea_type": row.get("idea_type"),
                "title": row.get("title"),
                "experiment": row.get("first_build_step"),
                "source_run_id": row.get("source_run_id"),
                "score": row.get("score"),
            }
        )
    return {
        "week_range": {"start": week_start, "end": week_end},
        "top_video_opportunities": by_type.get("video", [])[:10],
        "top_app_opportunities": by_type.get("app", [])[:10],
        "top_saas_opportunities": by_type.get("saas", [])[:10],
        "repeated_themes": repeated_themes,
        "rising_trends": rising_trends,
        "declining_topics": declining_topics,
        "ideas_to_ignore": low_confidence,
        "recommended_next_experiments": recommended_next_experiments,
        "execution_feedback": execution_feedback or {},
        "related_runs": run_ids,
        "counts": {
            "runs": len(runs),
            "signals": len(signals),
            "clusters": len(clusters),
            "opportunities": len(opportunities),
        },
        "opportunity_clusters": cluster_opportunities(opportunities)[:14],
    }


def _branch_opportunity_forms(seed: dict[str, Any]) -> list[dict[str, Any]]:
    title = _text(seed.get("title") or seed.get("topic") or seed.get("signal"), "Untitled signal")
    summary = _text(seed.get("summary") or seed.get("description") or seed.get("context"), "")
    niche = _text(seed.get("niche") or seed.get("category") or seed.get("topic_cluster"), "")
    audience = _text(seed.get("target_user") or seed.get("audience") or "General users")
    problem = _text(seed.get("problem_summary") or seed.get("problem") or summary, "Problem not specified.")
    base = {
        "source_title": title,
        "source_summary": summary,
        "source_niche": niche,
        "source_audience": audience,
        "source_problem": problem,
    }
    rows = [
        {
            "idea_type": "video",
            "title": f"{title}: short-form content angle",
            "summary": f"Create a repeatable short-form series around '{title}' for {audience}.",
            "problem_summary": problem,
            "target_user": audience,
            "why_now": f"Trend signal around '{title}' is rising.",
            "first_build_step": "Publish 3 hook variants and compare retention by channel.",
            "recommended_output_type": "dbvid",
            "score": 7.2,
        },
        {
            "idea_type": "app",
            "title": f"{title}: lightweight app opportunity",
            "summary": f"Ship a narrow app workflow to solve '{problem}' for {audience}.",
            "problem_summary": problem,
            "target_user": audience,
            "why_now": f"Recurring demand in niche '{niche or title}'.",
            "first_build_step": "Build one narrow workflow MVP and test with 5 users.",
            "recommended_output_type": "app_mvp",
            "score": 7.0,
        },
        {
            "idea_type": "saas",
            "title": f"{title}: SaaS workflow angle",
            "summary": f"Turn repeated pain around '{title}' into a paid B2B workflow tool.",
            "problem_summary": problem,
            "target_user": audience,
            "why_now": f"Monetizable recurring pain appears in '{niche or title}'.",
            "first_build_step": "Validate willingness to pay with 5 design partners.",
            "recommended_output_type": "saas_mvp",
            "score": 6.9,
        },
    ]
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(normalize_opportunity({**base, **row}))
    return out


async def _analyze_weekly_dataset(dataset: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return (
            {
                "status": "skipped",
                "reason": "OPENAI_API_KEY missing",
                "high_level_summary": "Weekly dataset generated without GPT-4o strategic analysis.",
            },
            None,
            None,
        )
    base_url = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    prompt = (
        "You are an opportunity strategist. Analyze this weekly dataset and return compact JSON with keys: "
        "high_level_opportunity_summary, strongest_areas_right_now, category_trends, suggested_experiments_next_week, "
        "signals_to_deprioritize, confidence_notes. Be concrete and concise.\n\n"
        f"DATASET:\n{json.dumps(dataset, ensure_ascii=True)[:24000]}"
    )
    body = {
        "model": "gpt-4o",
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You produce practical weekly strategy briefs for opportunity selection."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        content = _text((((payload.get("choices") or [{}])[0].get("message") or {}).get("content")), "")
        parsed = json.loads(content) if content else {}
        if not isinstance(parsed, dict):
            parsed = {"raw": parsed}
        parsed["status"] = "ok"
        return parsed, "gpt-4o", None
    except Exception as exc:  # noqa: BLE001
        return (
            {
                "status": "error",
                "high_level_summary": "Weekly dataset generated but strategic analysis failed.",
            },
            "gpt-4o",
            str(exc),
        )


@router.get("/api/modules/appgen/status")
def appgen_status() -> dict[str, str]:
    return {"module": "appgen", "status": "ready", "message": "IdeaFactory opportunity workflow available."}


@router.get("/api/appgen/promoted", response_model=list[PromotedIdeaRead])
def list_promoted(session: Session = Depends(get_session)) -> list[PromotedIdeaRead]:
    rows = session.exec(select(PromotedIdea).order_by(PromotedIdea.created_at.desc())).all()
    return [_to_read_model(row) for row in rows]


@router.post("/api/appgen/promoted", response_model=PromotedIdeaRead)
def create_promoted(payload: PromotedIdeaCreate, session: Session = Depends(get_session)) -> PromotedIdeaRead:
    existing = session.exec(
        select(PromotedIdea).where(
            PromotedIdea.source_run_id == payload.run_id,
            PromotedIdea.source_idea_id == payload.idea_id,
        )
    ).first()
    if existing:
        return _to_read_model(existing)

    normalized = normalize_opportunity(payload.raw_json, source_run_id=payload.run_id)
    raw_with_meta = dict(payload.raw_json)
    raw_with_meta.update(
        {
            "idea_type": normalized["idea_type"],
            "problem_summary": normalized["problem_summary"],
            "target_user": normalized["target_user"],
            "why_now": normalized["why_now"],
            "first_build_step": normalized["first_build_step"],
            "score": normalized["score"],
        }
    )
    title, summary = _extract_title_summary(raw_with_meta, payload.idea_id)
    row = PromotedIdea(
        source_run_id=payload.run_id,
        source_idea_id=payload.idea_id,
        title=title,
        summary=summary,
        idea_type=_text(normalized.get("idea_type"), "app"),
        problem_summary=_text(normalized.get("problem_summary")),
        target_user=_text(normalized.get("target_user")),
        why_now=_text(normalized.get("why_now")),
        first_build_step=_text(normalized.get("first_build_step")),
        raw_json=json.dumps(raw_with_meta, ensure_ascii=True),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_read_model(row)


@router.delete("/api/appgen/promoted/{promoted_id}")
def delete_promoted(promoted_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    row = session.get(PromotedIdea, promoted_id)
    if not row:
        raise HTTPException(status_code=404, detail="Promoted idea not found")
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.get("/weekly_reviews", response_model=list[WeeklyReviewRead])
@router.get("/api/appgen/weekly_reviews", response_model=list[WeeklyReviewRead])
def list_weekly_reviews(session: Session = Depends(get_session)) -> list[WeeklyReviewRead]:
    rows = session.exec(select(WeeklyReview).order_by(WeeklyReview.week_end.desc(), WeeklyReview.created_at.desc())).all()
    return [_to_weekly_read_model(row) for row in rows]


@router.get("/weekly_reviews/{review_id}", response_model=WeeklyReviewRead)
@router.get("/api/appgen/weekly_reviews/{review_id}", response_model=WeeklyReviewRead)
def get_weekly_review(review_id: str, session: Session = Depends(get_session)) -> WeeklyReviewRead:
    row = session.get(WeeklyReview, review_id)
    if not row:
        raise HTTPException(status_code=404, detail="weekly review not found")
    return _to_weekly_read_model(row)


@router.post("/weekly_reviews/generate", response_model=WeeklyReviewRead)
@router.post("/api/appgen/weekly_reviews/generate", response_model=WeeklyReviewRead)
async def generate_weekly_review(session: Session = Depends(get_session)) -> WeeklyReviewRead:
    service = get_topic_proxy_service()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    try:
        runs_payload = await service.request("GET", "/runs", params={"limit": 300}, use_cache=False)
        run_rows = _as_rows(runs_payload)
    except TopicProxyError:
        run_rows = []
    recent_runs: list[dict[str, Any]] = []
    for row in run_rows:
        ts = _to_dt(row.get("updated_at") or row.get("created_at") or row.get("started_at"))
        if ts is None or ts >= since:
            recent_runs.append(row)
    recent_run_ids = [_text(row.get("id") or row.get("run_id"), "") for row in recent_runs]
    recent_run_ids = [rid for rid in recent_run_ids if rid]

    opportunities: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []

    try:
        top_video_payload = await service.request("GET", "/video_ideas/top", params={"limit": 120}, use_cache=False)
        for row in _as_rows(top_video_payload):
            opportunities.append(normalize_opportunity(row))
    except TopicProxyError:
        pass
    try:
        top_ideas_payload = await service.request("GET", "/ideas/top", params={"limit": 180}, use_cache=False)
        for row in _as_rows(top_ideas_payload):
            opportunities.append(normalize_opportunity(row))
    except TopicProxyError:
        pass
    for run_id in recent_run_ids[:24]:
        try:
            signals_payload = await service.request("GET", "/signals", params={"run_id": run_id, "limit": 100}, use_cache=False)
            signals.extend(_as_rows(signals_payload))
        except TopicProxyError:
            pass
        try:
            clusters_payload = await service.request("GET", "/clusters", params={"run_id": run_id, "limit": 80}, use_cache=False)
            clusters.extend(_as_rows(clusters_payload))
        except TopicProxyError:
            pass
        try:
            ideas_payload = await service.request("GET", "/ideas", params={"run_id": run_id, "limit": 80}, use_cache=False)
            for row in _as_rows(ideas_payload):
                opportunities.append(normalize_opportunity(row, source_run_id=run_id))
        except TopicProxyError:
            pass

    deduped = dedupe_opportunities(opportunities)
    dataset = _build_weekly_dataset(
        runs=recent_runs,
        opportunities=deduped,
        signals=signals,
        clusters=clusters,
        execution_feedback=feedback_summary(session, days=14),
        now=now,
    )
    analysis, analysis_model, analysis_error = await _analyze_weekly_dataset(dataset)

    row = WeeklyReview(
        id=uuid.uuid4().hex,
        week_start=_text((dataset.get("week_range") or {}).get("start")),
        week_end=_text((dataset.get("week_range") or {}).get("end")),
        status="ready",
        generated_by="system",
        dataset_json=json.dumps(dataset, ensure_ascii=True),
        analysis_json=json.dumps(analysis, ensure_ascii=True),
        analysis_model=analysis_model,
        analysis_error=analysis_error,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_weekly_read_model(row)


@router.post("/api/appgen/transform/from-signal")
def transform_from_signal(payload: dict[str, Any]) -> dict[str, Any]:
    forms = _branch_opportunity_forms(payload if isinstance(payload, dict) else {})
    return {
        "source": payload if isinstance(payload, dict) else {},
        "forms": forms,
        "next_actions": [
            {"label": "Save best form to IdeaVault", "module": "IdeaVault"},
            {"label": "Run TopicInsights deep dive", "module": "TopicInsights"},
            {"label": "Queue follow-up in Orchestration", "module": "Orchestration"},
        ],
    }
