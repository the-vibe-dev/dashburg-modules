from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
def list_templates(request: Request) -> list[dict]:
    templates = request.app.state.agent_manager.list_templates()
    return [t.model_dump() for t in templates]


@router.get("/{template_id}")
def get_template(template_id: str, request: Request) -> dict:
    template = request.app.state.agent_manager.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return template.model_dump()
