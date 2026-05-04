from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.modules.skilled_agents.service import SkilledAgentsProxyError, SkilledAgentsProxyService, get_skilled_agents_proxy_service

router = APIRouter(prefix="/api/skilled-agents", tags=["skilled-agents"])


def _map_error(exc: SkilledAgentsProxyError) -> HTTPException:
    status = exc.upstream_status or 502
    if status < 100:
        status = 502
    return HTTPException(
        status_code=status,
        detail={
            "message": exc.message,
            "upstream_status": exc.upstream_status,
            "upstream_body": exc.upstream_body,
        },
    )


@router.get("/health")
async def health(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/health")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/skills")
async def list_skills(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/skills")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/skills/{skill_id}")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/skills")
async def create_skill(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/skills", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/templates")
async def list_templates(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/templates")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/templates/{template_id}")
async def get_template(template_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/templates/{template_id}")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/starter-templates")
async def list_starter_templates(
    top_only: bool = Query(default=False),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("GET", "/starter-templates", params={"top_only": top_only})
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/starter-templates/{slug}")
async def get_starter_template(slug: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/starter-templates/{slug}")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/starter-templates/import")
async def import_starter_template(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/starter-templates/import", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/starter-templates/import-batch")
async def import_starter_template_batch(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/starter-templates/import-batch", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/starter-templates/import-agency")
async def import_agency_templates(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/starter-templates/import-agency", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.delete("/starter-templates")
async def clear_starter_templates(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("DELETE", "/starter-templates")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents")
async def create_agent(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/agents", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/from-template")
async def create_agent_from_template(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/agents/from-template", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/preview-from-template")
async def preview_agent_from_template(
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", "/agents/preview-from-template", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents")
async def list_agents(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", "/agents")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.delete("/agents")
async def delete_agents(service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("DELETE", "/agents")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.patch("/agents/{agent_id}")
async def patch_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("PATCH", f"/agents/{agent_id}", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/skills")
async def attach_skill(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/skills", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.delete("/agents/{agent_id}/skills/{skill_id}")
async def detach_skill(
    agent_id: str,
    skill_id: str,
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("DELETE", f"/agents/{agent_id}/skills/{skill_id}")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/prepare")
async def prepare_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/prepare", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/deploy")
async def deploy_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/deploy", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/run")
async def run_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/run", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/dispatch")
async def dispatch_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/dispatch", json_body=service.inject_cluster_memory_context(payload))
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/memory-context")
async def get_memory_context(
    refresh: bool = Query(default=False),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    return service.get_cluster_memory_context(force_refresh=refresh)


@router.post("/agents/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/stop", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/mailbox/inbox")
async def get_mailbox_inbox(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/mailbox/inbox", params={"limit": limit})
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/mailbox/outbox")
async def get_mailbox_outbox(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/mailbox/outbox", params={"limit": limit})
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/mailbox/inbox")
async def post_mailbox_inbox(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/mailbox/inbox", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/mailbox/{message_id}/ack")
async def ack_mailbox_inbox(
    agent_id: str,
    message_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/mailbox/{message_id}/ack", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/logs")
async def get_logs(
    agent_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    run_id: str | None = Query(default=None),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if run_id:
        params["run_id"] = run_id
    try:
        return await service.request("GET", f"/agents/{agent_id}/logs", params=params)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/status")
async def get_status(agent_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/status")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/workspace")
async def get_workspace(agent_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/workspace")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/manifest")
async def get_manifest(agent_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/manifest")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/snapshots")
async def get_snapshots(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/snapshots", params={"limit": limit})
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.get("/agents/{agent_id}/latest-snapshot")
async def get_latest_snapshot(agent_id: str, service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service)) -> Any:
    try:
        return await service.request("GET", f"/agents/{agent_id}/latest-snapshot")
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/run-validation")
async def run_validation(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/run-validation", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc


@router.post("/agents/{agent_id}/run-smoke-test")
async def run_smoke_test(
    agent_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    service: SkilledAgentsProxyService = Depends(get_skilled_agents_proxy_service),
) -> Any:
    try:
        return await service.request("POST", f"/agents/{agent_id}/run-smoke-test", json_body=payload)
    except SkilledAgentsProxyError as exc:
        raise _map_error(exc) from exc
