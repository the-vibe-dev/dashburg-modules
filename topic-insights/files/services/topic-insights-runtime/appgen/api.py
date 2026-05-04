from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from appgen.config import load_config, save_config
from appgen.db import init_db, DB_PATH
from appgen.events import emit, sse_encode, subscribe, unsubscribe
from appgen.repo import (
    get_artifact,
    get_idea,
    get_run,
    list_artifacts,
    list_ideas,
    list_outbox,
    list_runs,
    run_metrics_summary,
    update_idea,
)
from appgen.schemas import (
    AppGenConfigResponse,
    ExportResponse,
    GenerateRequest,
    HealthResponse,
    IdeaUpdateRequest,
    MetricsSummaryResponse,
    PainExtractRequest,
    PainPointCreateRequest,
    StageResponse,
)
from appgen.services.audit import run_initial_audit, import_recent_oie_ideas
from appgen.services.exporter import export_to_appcreator
from appgen.services.generator import generate_ideas
from appgen.services.meta import analyze_meta, latest_meta
from appgen.services.pain import create_manual_pain_point, extract_pain_points, query_pain_points
from appgen.services.scorer import score_batch, score_idea
from appgen.services.stages import final_review, plan_generate, validate_idea

router = APIRouter(prefix="/api/appgen", tags=["appgen"])
_audit_done = False


def _ensure_init() -> None:
    global _audit_done
    init_db()
    if not _audit_done:
        try:
            run_initial_audit()
            _audit_done = True
        except Exception:
            _audit_done = True


@router.get("/health", response_model=HealthResponse)
def health():
    _ensure_init()
    return HealthResponse(ok=True, db_path=str(DB_PATH), schema_version=1)


@router.get("/config", response_model=AppGenConfigResponse)
def get_config():
    _ensure_init()
    return AppGenConfigResponse(**load_config())


@router.put("/config", response_model=AppGenConfigResponse)
def put_config(body: dict):
    _ensure_init()
    cfg = save_config(body)
    return AppGenConfigResponse(**cfg)


@router.post("/pain/extract")
def pain_extract(req: PainExtractRequest):
    _ensure_init()
    emit("appgen.run.created", {"run_type": "pain_extract"})
    return extract_pain_points(source_type=req.source_type, limit=req.limit, use_llm=req.use_llm)


@router.get("/pain")
def pain_list(source_type: str | None = None, q: str | None = None):
    _ensure_init()
    return {"items": query_pain_points(source_type=source_type, q=q)}


@router.post("/pain")
def pain_manual(req: PainPointCreateRequest):
    _ensure_init()
    pid = create_manual_pain_point(req.text, req.severity, req.category, req.source_ref)
    return {"id": pid}


@router.get("/ideas")
def ideas_list(status: str | None = None, q: str | None = None, sort: str = "updated_desc", needs_scoring: bool | None = None, imported: bool | None = None, category: str | None = None):
    _ensure_init()
    return {"items": list_ideas(status=status, q=q, sort=sort, needs_scoring=needs_scoring, imported=imported, category=category)}


@router.post("/ideas")
def ideas_create(body: dict):
    _ensure_init()
    from appgen.repo import insert_idea
    iid = insert_idea(body)
    emit("appgen.idea.created", {"idea_id": iid})
    return {"id": iid}


@router.get("/ideas/{idea_id}")
def ideas_get(idea_id: str):
    _ensure_init()
    idea = get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Not found")
    return idea


@router.put("/ideas/{idea_id}")
def ideas_put(idea_id: str, req: IdeaUpdateRequest):
    _ensure_init()
    idea = get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Not found")
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    update_idea(idea_id, patch)
    emit("appgen.idea.updated", {"idea_id": idea_id})
    return get_idea(idea_id)


@router.post("/generate")
def generate(req: GenerateRequest):
    _ensure_init()
    return generate_ideas(req.pain_point_ids, req.seed_text, req.count, req.constraints)


@router.post("/ideas/{idea_id}/score")
def score_single_idea(idea_id: str):
    _ensure_init()
    return score_idea(idea_id)


@router.post("/ideas/score/batch")
def score_ideas_batch(limit: int = 50):
    _ensure_init()
    return score_batch(limit=limit)


@router.get("/ideas/{idea_id}/artifacts")
def artifacts_for_idea(idea_id: str):
    _ensure_init()
    return {"items": list_artifacts(idea_id)}


@router.get("/artifacts/{artifact_id}")
def artifact_get(artifact_id: str):
    _ensure_init()
    a = get_artifact(artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    return a


@router.post("/ideas/{idea_id}/plan", response_model=StageResponse)
def plan(idea_id: str):
    _ensure_init()
    out = plan_generate(idea_id)
    return StageResponse(**out, provider="auto", model="auto")


@router.post("/ideas/{idea_id}/review", response_model=StageResponse)
def review(idea_id: str):
    _ensure_init()
    out = final_review(idea_id)
    return StageResponse(**out, provider="auto", model="auto")


@router.post("/ideas/{idea_id}/validate", response_model=StageResponse)
def validate(idea_id: str):
    _ensure_init()
    out = validate_idea(idea_id)
    return StageResponse(**out, provider="auto", model="auto")


@router.post("/meta/analyze")
def meta_analyze():
    _ensure_init()
    return analyze_meta()


@router.post("/import/oie")
def import_oie(limit: int = 200, score_limit: int = 100):
    _ensure_init()
    imported = import_recent_oie_ideas(limit=limit)
    scored = score_batch(limit=score_limit)
    return {"imported": imported, "scored": scored.get("scored", 0)}


@router.get("/meta/latest")
def meta_latest():
    _ensure_init()
    m = latest_meta()
    return m or {}


@router.post("/ideas/{idea_id}/export/appcreator", response_model=ExportResponse)
def export_appcreator(idea_id: str):
    _ensure_init()
    out = export_to_appcreator(idea_id)
    return ExportResponse(**out)


@router.get("/runs")
def runs_list(status: str | None = None, run_type: str | None = None, limit: int = 100):
    _ensure_init()
    return {"items": list_runs(status=status, run_type=run_type, limit=limit)}


@router.get("/runs/{run_id}")
def run_get(run_id: str):
    _ensure_init()
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    return run


@router.get("/runs/{run_id}/events")
def run_events(run_id: str):
    _ensure_init()
    events = [e for e in list_outbox(500) if (e.get("payload_json") or "").find(run_id) >= 0]
    return {"items": events}


@router.get("/runs/{run_id}/logs")
def run_logs(run_id: str):
    _ensure_init()
    # AppGen keeps durable metrics/events, not dedicated per-run text logs.
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "run_id": run_id,
        "logs": [
            f"status={run['status']}",
            f"provider={run.get('provider_used')}",
            f"model={run.get('model_used')}",
            f"error={run.get('error_text')}",
        ],
    }


@router.get("/events/stream")
async def events_stream(request: Request):
    _ensure_init()
    q = subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield sse_encode(item["topic"], item["payload"])
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/metrics/summary", response_model=MetricsSummaryResponse)
def metrics_summary():
    _ensure_init()
    return MetricsSummaryResponse(**run_metrics_summary())
