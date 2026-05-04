from __future__ import annotations

import os
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.trends_proxy.schemas import (
    TopicActionRequest,
    TopicFactoryImportRequest,
    TrendsExportRequest,
    TrendsRunStartRequest,
)
from app.modules.trends_proxy.service import TrendsProxyError, TrendsProxyService, get_trends_proxy_service

router = APIRouter(tags=["trends"])
logger = logging.getLogger("dashburg.trends_proxy")


def _raise_proxy_error(exc: TrendsProxyError) -> None:
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


def _raise_unexpected_error(exc: Exception) -> None:
    raise HTTPException(
        status_code=500,
        detail={
            "message": "Trends proxy internal error",
            "error": str(exc),
        },
    )


@router.get("/api/trends/runs")
async def trends_runs(service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/api/runs", use_cache=False)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.get("/api/trends/runs/{run_id}")
async def trends_run(run_id: str, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/api/runs/{run_id}", use_cache=False)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/runs/start")
async def trends_start_run(payload: TrendsRunStartRequest, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        body = payload.model_dump(exclude_none=True)
        # Observability: log outgoing run payload with no secrets.
        logger.info("trends.run.start payload=%s", body)
        return await service.request("POST", "/api/runs/start", json_body=body)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.delete("/api/trends/runs/{run_id}")
async def trends_delete_run(run_id: str, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("DELETE", f"/api/runs/{run_id}")
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/runs/{run_id}/cancel")
async def trends_cancel_run(run_id: str, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("POST", f"/api/runs/{run_id}/cancel")
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/runs/{run_id}/nudge")
async def trends_nudge_run(run_id: str, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("POST", f"/api/runs/{run_id}/nudge")
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.get("/api/trends/runs/{run_id}/results")
async def trends_run_results(
    run_id: str,
    limit: int = Query(default=25, ge=1, le=250),
    service: TrendsProxyService = Depends(get_trends_proxy_service),
) -> Any:
    try:
        return await service.request("GET", f"/api/runs/{run_id}/results", params={"limit": limit}, use_cache=False)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.get("/api/trends/runs/{run_id}/logs")
async def trends_run_logs(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    service: TrendsProxyService = Depends(get_trends_proxy_service),
) -> Any:
    try:
        return await service.request("GET", f"/api/runs/{run_id}/logs", params={"limit": limit, "offset": offset}, use_cache=False)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.get("/api/trends/topics/{topic_id}")
async def trends_topic(topic_id: str, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/api/topics/{topic_id}", use_cache=True)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/topics/{topic_id}/action")
async def trends_topic_action(
    topic_id: str,
    payload: TopicActionRequest,
    service: TrendsProxyService = Depends(get_trends_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/api/topics/{topic_id}/action", json_body=payload.model_dump(exclude_none=True))
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/export")
async def trends_export(payload: TrendsExportRequest, service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("POST", "/api/export", json_body=payload.model_dump(exclude_none=True))
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


async def _forward_topic_factory_import(payload: TopicFactoryImportRequest, service: TrendsProxyService) -> Any:
    import_url = os.getenv("DASHBURG_TOPIC_FACTORY_IMPORT_URL", "").strip()
    if import_url:
        base = service
        override_service = TrendsProxyService(base_url=import_url, cache_ttl_seconds=0.0)
        return await override_service.request("POST", "", json_body=payload.model_dump(exclude_none=True))

    topic_base_url = os.getenv("TOPIC_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    topic_service = TrendsProxyService(base_url=topic_base_url, cache_ttl_seconds=0.0)
    return await topic_service.request(
        "POST",
        "/api/v1/appgen/import-trends",
        json_body=payload.model_dump(exclude_none=True),
    )


@router.post("/api/trends/topic-factory/import-trends")
async def trends_import_topic_factory(
    payload: TopicFactoryImportRequest,
    service: TrendsProxyService = Depends(get_trends_proxy_service),
) -> Any:
    try:
        upstream = await _forward_topic_factory_import(payload, service)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)

    if isinstance(upstream, dict):
        return upstream

    return {
        "created_item_ids": [],
        "created_links": [],
        "raw": upstream,
    }


@router.post("/dashburg/api/topic-factory/import-trends")
async def trends_import_topic_factory_legacy(
    payload: TopicFactoryImportRequest,
    service: TrendsProxyService = Depends(get_trends_proxy_service),
) -> Any:
    return await trends_import_topic_factory(payload, service)


@router.get("/api/trends/health")
async def trends_health(service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        # Try a lightweight known endpoint to validate upstream reachability.
        data = await service.request("GET", "/api/runs", use_cache=False)
        if isinstance(data, list):
            count = len(data)
        else:
            count = None
        return {
            "status": "ok",
            "upstream": os.getenv("DASHBURG_TRENDS_API_BASE_URL", "http://127.0.0.1:8400"),
            "runs_count_hint": count,
        }
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.get("/api/trends/openai/key/status")
async def trends_openai_key_status(service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/api/openai/key/status", use_cache=False)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/openai/key")
async def trends_openai_key_set(payload: dict[str, Any], service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("POST", "/api/openai/key", json_body=payload)
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)


@router.post("/api/trends/openai/key/clear")
async def trends_openai_key_clear(service: TrendsProxyService = Depends(get_trends_proxy_service)) -> Any:
    try:
        return await service.request("POST", "/api/openai/key/clear")
    except TrendsProxyError as exc:
        _raise_proxy_error(exc)
    except Exception as exc:
        _raise_unexpected_error(exc)
