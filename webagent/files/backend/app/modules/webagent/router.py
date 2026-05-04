from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db.session import get_session
from app.modules.webagent.service import (
    create_webagent_run,
    execute_webagent_tool,
    execute_webagent_action,
    get_webagent_artifact_content,
    get_webagent_discovery,
    get_webagent_generated_tests,
    get_webagent_live_session,
    get_webagent_run_artifacts,
    get_webagent_run_detail,
    get_webagent_run_logs,
    get_webagent_run_replay_assets,
    get_webagent_run_screenshots,
    list_webagent_reports,
    list_webagent_runs,
    mark_webagent_run_useful,
    retry_webagent_run,
    save_webagent_report,
    webagent_overview,
    webagent_status,
)

router = APIRouter(prefix="/api/webagent", tags=["webagent"])


class WebAgentRunCreateRequest(BaseModel):
    target_url: str = Field(min_length=8)
    run_type: str = Field(min_length=3)
    node_id: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class WebAgentRunUsefulRequest(BaseModel):
    is_useful: bool = True


class WebAgentSaveReportRequest(BaseModel):
    title: str = ""


class WebAgentSessionCreateRequest(BaseModel):
    target_url: str = Field(min_length=8)
    node_id: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=90, ge=5, le=600)


class WebAgentActionRequest(BaseModel):
    node_id: str | None = None
    session_id: str | None = None
    action: str = ""
    selector: str | None = None
    url: str | None = None
    value: str | int | float | bool | dict[str, Any] | list[Any] | None = None
    text: str | None = None
    files: list[str] = Field(default_factory=list)
    key: str | None = None
    button: str | None = None
    count: int | None = None
    index: int | None = None
    label: str | None = None
    x: float | None = None
    y: float | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    state: str | None = None
    timeout_ms: int | None = None
    wait_for: str | None = None
    script: str | None = None
    expression: str | None = None
    screenshot_name: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    retries: int | None = None
    retry_backoff_ms: int | None = None
    selector_strategy: str | None = None
    strict_targeting: bool | None = None
    run_mode: str | None = None
    targeting: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: int = Field(default=90, ge=5, le=600)


@router.get("/overview")
def get_overview(session: Session = Depends(get_session)) -> dict[str, Any]:
    return webagent_overview(session)


@router.get("/runs")
def get_runs(
    status: str | None = None,
    saved_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {"items": list_webagent_runs(session, status=status, saved_only=saved_only, limit=limit)}


@router.post("/runs")
def post_run(payload: WebAgentRunCreateRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return create_webagent_run(
        session,
        target_url=payload.target_url,
        run_type=payload.run_type,
        node_id=payload.node_id,
        settings=payload.settings,
        notes=payload.notes,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_run_detail(session, run_id)


@router.get("/runs/{run_id}/live")
def get_run_live(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_live_session(session, run_id)


@router.get("/runs/{run_id}/artifacts")
def get_run_artifacts(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_run_artifacts(session, run_id)


@router.get("/runs/{run_id}/artifacts/content")
def get_run_artifact_content(run_id: str, path: str = Query(min_length=1), session: Session = Depends(get_session)) -> Response:
    content = get_webagent_artifact_content(session, run_id, path)
    media_type, _ = mimetypes.guess_type(path)
    return Response(content=content, media_type=media_type or "application/octet-stream")


@router.get("/runs/{run_id}/logs")
def get_run_logs(run_id: str, limit: int = Query(default=400, ge=1, le=2000), session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_run_logs(session, run_id, limit=limit)


@router.get("/runs/{run_id}/screenshots")
def get_run_screenshots(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_run_screenshots(session, run_id)


@router.get("/runs/{run_id}/replay")
def get_run_replay(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_run_replay_assets(session, run_id)


@router.get("/runs/{run_id}/generated-tests")
def get_run_generated_tests(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_generated_tests(session, run_id)


@router.get("/runs/{run_id}/discovery")
def get_run_discovery(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_webagent_discovery(session, run_id)


@router.post("/runs/{run_id}/retry")
def post_retry(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return retry_webagent_run(session, run_id)


@router.post("/runs/{run_id}/save-report")
def post_save_report(run_id: str, payload: WebAgentSaveReportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return save_webagent_report(session, run_id, title=payload.title)


@router.post("/runs/{run_id}/useful")
def post_mark_useful(run_id: str, payload: WebAgentRunUsefulRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return mark_webagent_run_useful(session, run_id, is_useful=payload.is_useful)


@router.get("/reports")
def get_reports(limit: int = Query(default=200, ge=1, le=500), session: Session = Depends(get_session)) -> dict[str, Any]:
    return {"items": list_webagent_reports(session, limit=limit)}


@router.get("/status")
def get_status(node_id: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    return webagent_status(session, requested_node_id=node_id)


@router.post("/sessions")
def post_session(payload: WebAgentSessionCreateRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return execute_webagent_action(
        session,
        action="start_session",
        node_id=payload.node_id,
        payload={
            "target_url": payload.target_url,
            "url": payload.target_url,
            "options": payload.settings,
        },
        timeout_seconds=payload.timeout_seconds,
    )


@router.get("/sessions/{session_id}")
def get_session_status(
    session_id: str,
    node_id: str | None = None,
    timeout_seconds: int = Query(default=60, ge=5, le=600),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return execute_webagent_action(
        session,
        action="session_status",
        node_id=node_id,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
    )


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    node_id: str | None = None,
    timeout_seconds: int = Query(default=60, ge=5, le=600),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return execute_webagent_action(
        session,
        action="stop_session",
        node_id=node_id,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
    )


@router.post("/sessions/{session_id}/actions")
def post_session_action(session_id: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    body = payload.model_dump()
    action = str(body.pop("action") or "").strip()
    body.pop("session_id", None)
    node_id = body.pop("node_id", None)
    timeout_seconds = int(body.pop("timeout_seconds", 90) or 90)
    return execute_webagent_action(
        session,
        action=action,
        node_id=node_id,
        session_id=session_id,
        payload=body,
        timeout_seconds=timeout_seconds,
    )


@router.post("/actions")
def post_action(payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    body = payload.model_dump()
    action = str(body.pop("action") or "").strip()
    sid = str(body.pop("session_id") or "").strip() or None
    node_id = body.pop("node_id", None)
    timeout_seconds = int(body.pop("timeout_seconds", 90) or 90)
    return execute_webagent_action(
        session,
        action=action,
        node_id=node_id,
        session_id=sid,
        payload=body,
        timeout_seconds=timeout_seconds,
    )


@router.post("/tools/{tool_name}")
def post_tool(tool_name: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    body = payload.model_dump()
    sid = str(body.pop("session_id") or "").strip() or None
    node_id = body.pop("node_id", None)
    timeout_seconds = int(body.pop("timeout_seconds", 90) or 90)
    body.pop("action", None)
    return execute_webagent_tool(
        session,
        tool_name=tool_name,
        node_id=node_id,
        session_id=sid,
        payload=body,
        timeout_seconds=timeout_seconds,
    )


def _shortcut_action(
    session: Session,
    *,
    session_id: str,
    action: str,
    payload: WebAgentActionRequest,
) -> dict[str, Any]:
    body = payload.model_dump()
    body.pop("action", None)
    body.pop("session_id", None)
    node_id = body.pop("node_id", None)
    timeout_seconds = int(body.pop("timeout_seconds", 90) or 90)
    return execute_webagent_action(
        session,
        action=action,
        node_id=node_id,
        session_id=session_id,
        payload=body,
        timeout_seconds=timeout_seconds,
    )


@router.post("/sessions/{session_id}/navigate")
def post_session_navigate(session_id: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _shortcut_action(session, session_id=session_id, action="goto", payload=payload)


@router.post("/sessions/{session_id}/click")
def post_session_click(session_id: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _shortcut_action(session, session_id=session_id, action="click", payload=payload)


@router.post("/sessions/{session_id}/fill")
def post_session_fill(session_id: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _shortcut_action(session, session_id=session_id, action="fill", payload=payload)


@router.post("/sessions/{session_id}/upload")
def post_session_upload(session_id: str, payload: WebAgentActionRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _shortcut_action(session, session_id=session_id, action="set_input_files", payload=payload)
