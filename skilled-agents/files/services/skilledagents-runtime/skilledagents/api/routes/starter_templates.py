from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/starter-templates", tags=["starter-templates"])


@router.get("")
def list_starter_templates(
    request: Request,
    top_only: bool = Query(default=False),
) -> list[dict]:
    return request.app.state.starter_template_service.list_templates(top_only=top_only)


@router.get("/{slug}")
def get_starter_template(slug: str, request: Request) -> dict:
    template = request.app.state.starter_template_service.get_template(slug)
    if template is None:
        raise HTTPException(status_code=404, detail="starter template not found")
    return template


@router.post("/import")
def import_starter_pack(payload: dict, request: Request) -> dict:
    zip_path = str(payload.get("zip_path") or "").strip()
    if not zip_path:
        raise HTTPException(status_code=400, detail="zip_path is required")
    pack_version = payload.get("pack_version")
    try:
        return request.app.state.starter_template_service.import_pack(zip_path=zip_path, pack_version=pack_version)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import-batch")
def import_starter_pack_batch(payload: dict, request: Request) -> dict:
    zip_paths = payload.get("zip_paths") or []
    if not isinstance(zip_paths, list) or not zip_paths:
        raise HTTPException(status_code=400, detail="zip_paths[] is required")
    try:
        return request.app.state.starter_template_service.import_batch([str(path) for path in zip_paths])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import-agency")
def import_agency_templates(payload: dict, request: Request) -> dict:
    root_path = str(payload.get("root_path") or "").strip()
    if not root_path:
        raise HTTPException(status_code=400, detail="root_path is required")
    try:
        return request.app.state.starter_template_service.import_agency_templates(
            root_path=root_path,
            purge_first=bool(payload.get("purge_first")),
            seed_top_agents=bool(payload.get("seed_top_agents", True)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("")
def clear_starter_templates(request: Request) -> dict:
    return request.app.state.starter_template_service.clear_templates()
