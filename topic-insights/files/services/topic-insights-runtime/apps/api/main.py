from __future__ import annotations
import logging
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.logging import setup_logging
from core.http_client import init_async_client, shutdown_async_client
from storage.db import init_db
from storage.repository import list_clusters, get_cluster, list_ideas, get_counts, rawpost_counts_by_source, list_run_events, provider_stats
from core.orchestrator import run_end_to_end, RunParams, run_auto_discovery
from appgen.api import router as appgen_router
from appgen.db import init_db as init_appgen_db
from appgen.repo import list_ideas as appgen_list_ideas, get_idea as appgen_get_idea, list_artifacts as appgen_list_artifacts, list_runs as appgen_list_runs, get_run as appgen_get_run, list_outbox as appgen_list_outbox
from appgen.config import load_config as appgen_load_config, save_config as appgen_save_config
from apps.api import api_v1
from apps.api.api_v1 import router as api_v1_router

app = FastAPI(title="Opportunity Intelligence Engine")
app.include_router(appgen_router)
app.include_router(api_v1_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.1.153",
        "http://dashburg.local",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.1\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="apps/api/templates")

# Serve latest report assets (logos)
from core.config import settings
from pathlib import Path
reports_dir = Path(settings.data_dir) / "reports"
reports_dir.mkdir(parents=True, exist_ok=True)
app.mount('/reports', StaticFiles(directory=str(reports_dir), html=True), name='reports')

@app.on_event("startup")
def _startup():
    from core.config import settings
    log_file = str(Path(settings.data_dir) / "run.log")
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO, log_file=log_file)
    logging.getLogger(__name__).info("api_startup")
    init_async_client()
    init_db()
    init_appgen_db()

@app.on_event("shutdown")
def _shutdown():
    shutdown_async_client()

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    log_text = ""
    try:
        log_path = Path(settings.data_dir) / "run.log"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            log_text = "\n".join(lines[-200:])
    except Exception:
        log_text = ""
    clusters = list_clusters(limit=50)
    return templates.TemplateResponse(
        "index.html", {"request": request, "clusters": clusters, "log_text": log_text, "settings": settings}
    )

@app.get("/cluster/{cluster_id}", response_class=HTMLResponse)
def cluster_page(request: Request, cluster_id: str):
    cluster = get_cluster(cluster_id)
    ideas = list_ideas(cluster_id=cluster_id, limit=50)
    if not cluster:
        return templates.TemplateResponse("not_found.html", {"request": request, "message": "Cluster not found"})
    return templates.TemplateResponse("cluster.html", {"request": request, "cluster": cluster, "ideas": ideas})

@app.get("/debug", response_class=HTMLResponse)
def debug_page(request: Request):
    counts = get_counts()
    sources = rawpost_counts_by_source()
    events = list_run_events(limit=50)
    last_event = events[0] if events else None
    calls = provider_stats(limit=100)
    total_calls = len(calls)
    cache_hits = len([c for c in calls if c.cache_hit])
    cache_hit_rate = (cache_hits / total_calls) * 100 if total_calls else 0.0
    return templates.TemplateResponse(
        "debug.html",
        {
            "request": request,
            "db_path": settings.database_url,
            "counts": counts,
            "sources": sources,
            "events": events,
            "last_event": last_event,
            "calls": calls,
            "cache_hit_rate": cache_hit_rate,
        },
    )

@app.post("/run")
async def run_scan(request: Request):
    log = logging.getLogger(__name__)
    form = await request.form()
    query = str(form.get("query") or "").strip()
    topic = str(form.get("topic") or "").strip() or "general"
    limit = int(form.get("limit") or 40)
    enable_youtube = str(form.get("enable_youtube") or "false").lower() in ("1","true","yes","on")
    enable_x_trends = str(form.get("enable_x_trends") or "false").lower() in ("1","true","yes","on")
    ingest_overrides = {}
    for key in [
        "reddit_max_posts",
        "reddit_max_comment_posts",
        "reddit_max_comments_per_post",
        "web_search_max_results",
        "youtube_max_videos",
        "youtube_max_comments_per_video",
        "youtube_search_max_results",
    ]:
        val = form.get(key)
        if val is not None and str(val).strip() != "":
            ingest_overrides[key] = int(val)
    log.info("run_request query=%s topic=%s limit=%s enable_youtube=%s", query, topic, limit, enable_youtube)
    run_end_to_end(
        RunParams(
            query=query,
            topic=topic,
            limit=limit,
            enable_youtube=enable_youtube,
            sources={"x_trends": bool(enable_x_trends)},
            ingest_overrides=ingest_overrides,
        )
    )
    log.info("run_request_complete query=%s topic=%s", query, topic)
    return RedirectResponse(url="/", status_code=303)

# API endpoints
@app.get("/api/clusters")
def api_clusters(limit: int = 50):
    return [c.model_dump() for c in list_clusters(limit=limit)]

@app.get("/api/ideas")
def api_ideas(cluster_id: str | None = None, limit: int = 100):
    return [i.model_dump() for i in list_ideas(cluster_id=cluster_id, limit=limit)]


@app.post("/api/runs/start")
def api_runs_start(body: api_v1.TargetedRunIn):
    return api_v1.run_start_compat(body)


@app.get("/api/runs")
def api_runs(limit: int = 50):
    out = api_v1.runs(limit=limit)
    return out.get("jobs", [])


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    return api_v1.run_detail(run_id)


@app.get("/api/runs/{run_id}/results")
def api_run_results(run_id: str, limit: int = 25):
    return api_v1.run_results(run_id, limit=limit)


@app.post("/auto-run")
async def auto_run(request: Request):
    from core.config import settings
    log = logging.getLogger(__name__)
    form = await request.form()
    ideas_per_run = int(form.get("ideas_per_run") or settings.auto_discovery_ideas_per_run)
    target_topics = int(form.get("target_topics") or settings.auto_discovery_target_topics)
    limit_per_topic = int(form.get("limit_per_topic") or settings.auto_discovery_limit_per_topic)
    ingest_overrides = {}
    for key in [
        "reddit_max_posts",
        "reddit_max_comment_posts",
        "reddit_max_comments_per_post",
        "web_search_max_results",
        "youtube_max_videos",
        "youtube_max_comments_per_video",
        "youtube_search_max_results",
    ]:
        val = form.get(key)
        if val is not None and str(val).strip() != "":
            ingest_overrides[key] = int(val)
    log.info("auto_run_request ideas_per_run=%s target_topics=%s", ideas_per_run, target_topics)
    try:
        run_auto_discovery(
            ideas_per_run=ideas_per_run,
            target_topics=target_topics,
            limit_per_topic=limit_per_topic,
            ingest_overrides=ingest_overrides,
        )
        log.info("auto_run_complete")
    except Exception as exc:
        log.exception("auto_run_failed error=%s", exc)
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    log_path = Path(settings.data_dir) / "run.log"

    async def event_stream():
        pos = 0
        try:
            if log_path.exists():
                size = log_path.stat().st_size
                pos = max(0, size - 200_000)
        except Exception:
            pos = 0
        buffer = ""
        while True:
            try:
                if await request.is_disconnected():
                    break
                if log_path.exists():
                    try:
                        size = log_path.stat().st_size
                        if size < pos:
                            pos = 0
                    except Exception:
                        pass
                    with log_path.open("r", encoding="utf-8") as f:
                        f.seek(pos)
                        chunk = f.read(8192)
                        if chunk:
                            pos = f.tell()
                            data = buffer + chunk
                            lines = data.splitlines()
                            if not data.endswith("\n"):
                                buffer = lines.pop() if lines else data
                            else:
                                buffer = ""
                            for line in lines:
                                yield f"data: {line}\n\n"
                        else:
                            yield ": keepalive\n\n"
                else:
                    yield ": log_file_missing\n\n"
            except Exception as e:
                yield f"data: log_stream_error {e}\n\n"
            import asyncio
            # Heartbeat to keep connection open across proxies
            await asyncio.sleep(0.5)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.get("/api/logs/tail")
def tail_logs(offset: int = 0, max_lines: int = 200):
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
        chunk = f.read(50_000)
        new_offset = f.tell()
    lines = chunk.splitlines()[:max_lines]
    return {"offset": new_offset, "lines": lines}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/appgen/ideas", response_class=HTMLResponse)
def appgen_ideas_page(request: Request, status: str | None = None, q: str | None = None, sort: str = "overall_score_desc", needs_scoring: bool | None = None, imported: bool | None = None, category: str | None = None):
    ideas = appgen_list_ideas(status=status, q=q, sort=sort, needs_scoring=needs_scoring, imported=imported, category=category)
    return templates.TemplateResponse(
        "appgen_ideas.html",
        {"request": request, "ideas": ideas, "filters": {"status": status, "q": q, "sort": sort, "needs_scoring": needs_scoring, "imported": imported, "category": category}},
    )


@app.get("/appgen/ideas/{idea_id}", response_class=HTMLResponse)
def appgen_idea_detail_page(request: Request, idea_id: str):
    idea = appgen_get_idea(idea_id)
    if not idea:
        return templates.TemplateResponse("not_found.html", {"request": request, "message": "AppGen idea not found"})
    artifacts = appgen_list_artifacts(idea_id)
    runs = [r for r in appgen_list_runs(limit=200) if r.get("idea_id") == idea_id]
    return templates.TemplateResponse(
        "appgen_idea_detail.html",
        {"request": request, "idea": idea, "artifacts": artifacts, "runs": runs},
    )


@app.get("/appgen/runs", response_class=HTMLResponse)
def appgen_runs_page(request: Request, status: str | None = None, run_type: str | None = None, limit: int = 100):
    runs = appgen_list_runs(status=status, run_type=run_type, limit=limit)
    return templates.TemplateResponse("appgen_runs.html", {"request": request, "runs": runs, "filters": {"status": status, "run_type": run_type}})


@app.get("/appgen/runs/{run_id}", response_class=HTMLResponse)
def appgen_run_detail_page(request: Request, run_id: str):
    run = appgen_get_run(run_id)
    if not run:
        return templates.TemplateResponse("not_found.html", {"request": request, "message": "AppGen run not found"})
    events = [e for e in appgen_list_outbox(500) if (e.get("payload_json") or "").find(run_id) >= 0]
    return templates.TemplateResponse("appgen_run_detail.html", {"request": request, "run": run, "events": events})


@app.get("/appgen/settings", response_class=HTMLResponse)
def appgen_settings_page(request: Request):
    cfg = appgen_load_config()
    return templates.TemplateResponse("appgen_settings.html", {"request": request, "cfg": cfg})


@app.post("/appgen/settings")
async def appgen_settings_save(request: Request):
    form = await request.form()
    cfg = appgen_load_config()
    wf = cfg["appgen"]["workflow"]
    wf["allow_stub_persistence"] = str(form.get("allow_stub_persistence") or "false").lower() in ("1", "true", "yes", "on")
    wf["dedupe_window_days"] = int(form.get("dedupe_window_days") or wf.get("dedupe_window_days", 180))
    wf["high_score_threshold"] = float(form.get("high_score_threshold") or wf.get("high_score_threshold", 8.2))
    wf["ideas_per_generate"] = int(form.get("ideas_per_generate") or wf.get("ideas_per_generate", 5))
    wf["min_distinct_categories"] = int(form.get("min_distinct_categories") or wf.get("min_distinct_categories", 3))
    wf["min_distinct_pain_themes"] = int(form.get("min_distinct_pain_themes") or wf.get("min_distinct_pain_themes", 3))
    appgen_save_config(cfg)
    return RedirectResponse(url="/appgen/settings", status_code=303)
