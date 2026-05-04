from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.modules.remote_ops.service import ensure_settings as ensure_remote_settings
from app.modules.schedule_ops.service import (
    apply_node_schedule,
    create_diagnostic_delegate,
    get_node_schedule,
    get_node_schedule_status,
    list_schedule_status,
    list_schedule_nodes,
    map_runner_error,
    put_node_schedule,
)

router = APIRouter(prefix="/api/scheduleops", tags=["schedule-ops"])


def _allow_client_or_admin(
    admin_token: str | None = Header(default=None, alias="X-RemoteOps-Admin-Token"),
    client_token: str | None = Header(default=None, alias="X-RemoteOps-Client-Token"),
    admin_token_q: str | None = Query(default=None, alias="admin_token"),
    client_token_q: str | None = Query(default=None, alias="client_token"),
    session: Session = Depends(get_session),
) -> None:
    expected_admin = os.getenv("REMOTEOPS_ADMIN_TOKEN", "").strip()
    if not expected_admin:
        return
    provided_admin = admin_token or admin_token_q
    provided_client = client_token or client_token_q
    if provided_admin == expected_admin:
        return
    remote_settings = ensure_remote_settings(session)
    if remote_settings.client_token and provided_client == remote_settings.client_token:
        return
    raise HTTPException(status_code=401, detail="missing or invalid token")


@router.get("/nodes")
def get_nodes(
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return {"items": list_schedule_nodes(session)}


@router.get("/nodes/{node_id}")
def get_node(node_id: str, session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    try:
        return get_node_schedule(session, node_id)
    except Exception as exc:
        status, detail = map_runner_error(exc)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/nodes/{node_id}/status")
def get_node_status(node_id: str, session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    try:
        return get_node_schedule_status(session, node_id)
    except Exception as exc:
        status, detail = map_runner_error(exc)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.put("/nodes/{node_id}")
def put_node(
    node_id: str,
    payload: dict[str, Any],
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    try:
        return put_node_schedule(session, node_id, payload if isinstance(payload, dict) else {})
    except Exception as exc:
        status, detail = map_runner_error(exc)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/nodes/{node_id}/apply")
def post_apply(
    node_id: str,
    payload: dict[str, Any] | None = None,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    _ = payload
    try:
        return apply_node_schedule(session, node_id)
    except Exception as exc:
        status, detail = map_runner_error(exc)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/status")
def get_cluster_status(session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    return list_schedule_status(session)


@router.post("/diagnostics/delegate")
def post_delegate_diagnostic(
    payload: dict[str, Any],
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    try:
        job = create_diagnostic_delegate(session, payload if isinstance(payload, dict) else {})
        return {"job": job}
    except Exception as exc:
        status, detail = map_runner_error(exc)
        raise HTTPException(status_code=status, detail=detail) from exc
