from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.modules.discord.service import (
    append_memory_note,
    approve_request,
    bootstrap_discord_session,
    dispatch_stub,
    dispatch_targets,
    ensure_settings,
    get_audit,
    get_request_detail,
    get_status_payload,
    ingest_dispatch_request,
    list_approvals,
    list_requests,
    policy_evaluate_preview,
    register_worker,
    reject_request,
    reindex_memory,
    resolve_discord_session,
    run_connectivity_test,
    settings_to_public,
    update_settings,
    worker_heartbeat,
    worker_poll,
    worker_status,
    worker_submit_result,
)
from app.modules.remote_ops.service import ensure_settings as ensure_remote_settings
from app.schemas.discord import (
    DiscordApprovalDecisionRequest,
    DiscordConnectivityTestRequest,
    DiscordDispatchRequestIngest,
    DiscordIntegrationSettingsUpdate,
    DiscordMemoryAppendRequest,
    DiscordMemoryReindexRequest,
    DiscordPolicyEvaluateRequest,
    DiscordSessionBootstrapRequest,
    DiscordSessionResolveRequest,
    DispatchWorkerHeartbeatRequest,
    DispatchWorkerPollRequest,
    DispatchWorkerRegisterRequest,
    DispatchWorkerResultRequest,
)

router = APIRouter(prefix="/api/discord", tags=["discord"])


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


def _require_bridge_auth(
    bridge_key: str | None = Header(default=None, alias="X-Dashburg-Bridge-Key"),
    session: Session = Depends(get_session),
) -> None:
    settings = ensure_settings(session)
    if not settings.bridge_auth_enabled:
        return
    expected = (settings.bridge_api_key or os.getenv("DISCORD_BRIDGE_SHARED_KEY", "")).strip()
    if not expected:
        raise HTTPException(status_code=503, detail="discord bridge key not configured")
    if str(bridge_key or "").strip() != expected:
        raise HTTPException(status_code=401, detail="invalid bridge key")


def _require_worker_auth(worker_token: str | None = Header(default=None, alias="X-Discord-Worker-Token")) -> None:
    expected = os.getenv("DISCORD_WORKER_TOKEN", "").strip()
    if not expected:
        return
    if str(worker_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="invalid worker token")


@router.get("/settings")
def get_discord_settings(session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    row = ensure_settings(session)
    return settings_to_public(row)


@router.post("/settings")
def post_discord_settings(
    payload: DiscordIntegrationSettingsUpdate,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = update_settings(session, payload.model_dump(exclude_none=True))
    return settings_to_public(row)


@router.get("/status")
async def get_discord_status(session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    row = ensure_settings(session)
    return await get_status_payload(session, row)


@router.post("/test")
async def post_discord_test(
    payload: DiscordConnectivityTestRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return await run_connectivity_test(session, row, payload.model_dump())


@router.post("/reindex-memory")
def post_discord_reindex_memory(
    payload: DiscordMemoryReindexRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return reindex_memory(session, row, dry_run=payload.dry_run)


@router.post("/memory/append")
def post_discord_memory_append(
    payload: DiscordMemoryAppendRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return append_memory_note(session, row, note=payload.note, kind=payload.kind, relevance=payload.relevance, dry_run=payload.dry_run)


@router.get("/dispatch-targets")
def get_discord_dispatch_targets(session: Session = Depends(get_session), _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    row = ensure_settings(session)
    return dispatch_targets(session, row)


@router.post("/session/bootstrap")
def post_discord_session_bootstrap(
    payload: DiscordSessionBootstrapRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return bootstrap_discord_session(session, row, payload.model_dump())


@router.post("/session/resolve")
def post_discord_session_resolve(
    payload: DiscordSessionResolveRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return resolve_discord_session(session, row, payload.model_dump())


@router.post("/policy/evaluate")
def post_discord_policy_evaluate(
    payload: DiscordPolicyEvaluateRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return policy_evaluate_preview(session, row, payload.model_dump())


@router.post("/dispatch")
async def post_discord_dispatch(
    payload: DiscordDispatchRequestIngest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return await ingest_dispatch_request(session, row, payload.model_dump())


@router.post("/ingest")
async def post_discord_ingest_from_bridge(
    payload: DiscordDispatchRequestIngest,
    session: Session = Depends(get_session),
    _: None = Depends(_require_bridge_auth),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return await ingest_dispatch_request(session, row, payload.model_dump())


@router.get("/bridge/requests/{request_id}")
def get_bridge_request_detail(
    request_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(_require_bridge_auth),
) -> dict[str, Any]:
    return get_request_detail(session, request_id)


@router.get("/requests")
def get_discord_requests(
    limit: int = Query(default=100, ge=1, le=500),
    status: str = Query(default=""),
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return list_requests(session, limit=limit, status=status)


@router.get("/requests/{request_id}")
def get_discord_request_detail(
    request_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return get_request_detail(session, request_id)


@router.get("/approvals")
def get_discord_approvals(
    limit: int = Query(default=100, ge=1, le=500),
    status: str = Query(default="pending"),
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return list_approvals(session, status=status, limit=limit)


@router.post("/approve")
def post_discord_approve(
    payload: DiscordApprovalDecisionRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return approve_request(session, row, payload.model_dump())


@router.post("/reject")
def post_discord_reject(
    payload: DiscordApprovalDecisionRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    row = ensure_settings(session)
    return reject_request(session, row, payload.model_dump())


@router.get("/audit/{audit_id}")
def get_discord_audit(
    audit_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return get_audit(session, audit_id)


@router.get("/workers")
def get_discord_workers(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    _: None = Depends(_allow_client_or_admin),
) -> dict[str, Any]:
    return worker_status(session, limit=limit)


@router.post("/worker/register")
def post_discord_worker_register(
    payload: DispatchWorkerRegisterRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_require_worker_auth),
) -> dict[str, Any]:
    return register_worker(session, payload.model_dump())


@router.post("/worker/heartbeat")
def post_discord_worker_heartbeat(
    payload: DispatchWorkerHeartbeatRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_require_worker_auth),
) -> dict[str, Any]:
    return worker_heartbeat(session, payload.model_dump())


@router.post("/worker/poll")
def post_discord_worker_poll(
    payload: DispatchWorkerPollRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_require_worker_auth),
) -> dict[str, Any]:
    return worker_poll(session, payload.model_dump())


@router.post("/worker/requests/{request_id}/result")
def post_discord_worker_result(
    request_id: str,
    payload: DispatchWorkerResultRequest,
    session: Session = Depends(get_session),
    _: None = Depends(_require_worker_auth),
) -> dict[str, Any]:
    return worker_submit_result(session, request_id, payload.model_dump())


@router.post("/dispatch/stub")
def post_discord_dispatch_stub(payload: dict[str, Any], _: None = Depends(_allow_client_or_admin)) -> dict[str, Any]:
    return dispatch_stub(payload)
