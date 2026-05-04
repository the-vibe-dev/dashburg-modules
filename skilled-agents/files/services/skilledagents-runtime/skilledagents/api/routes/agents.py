from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from skilledagents.models.agent import (
    AgentActionResponse,
    AgentCreate,
    AgentDispatchRequest,
    AgentMailboxMessageCreate,
    AgentOut,
    AgentRunRequest,
    AgentStatus,
    AgentUpdate,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "agent"


def _get_agent_or_404(request: Request, agent_id: str) -> dict:
    agent = request.app.state.agent_manager.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


def _deploy_mode_settings(mode: str) -> dict[str, Any]:
    m = mode.lower()
    if m == "safe":
        return {"sandbox_mode": "read-only", "network_access": False, "yolo_mode": False}
    if m == "sandboxed":
        return {"sandbox_mode": "workspace-write", "network_access": False, "yolo_mode": False}
    if m == "networked":
        return {"sandbox_mode": "workspace-write", "network_access": True, "yolo_mode": False}
    if m == "yolo":
        return {"sandbox_mode": "danger-full-access", "network_access": True, "yolo_mode": True}
    return {"sandbox_mode": "workspace-write", "network_access": False, "yolo_mode": False}


def _mode_conflicts(template: dict, mode: str) -> list[str]:
    badges = template.get("compatibility_badges") or {}
    warnings: list[str] = []
    lower = mode.lower()
    if badges.get("requires_network") and lower in {"safe", "sandboxed"}:
        warnings.append("template requires network access, but selected mode disables network")
    if badges.get("requires_browser") and not template.get("uses_webagent") and lower == "safe":
        warnings.append("template requires browser runtime locally; safe mode may block this")
    return warnings


def _build_template_preview(template: dict, deploy_mode: str) -> dict[str, Any]:
    return {
        "files_to_create": template.get("files_to_create", []),
        "skills_to_attach": template.get("skills_to_attach", []),
        "dependencies_to_install": template.get("dependencies_to_install", []),
        "recommended_deploy_mode": template.get("recommended_deploy_mode", "sandboxed"),
        "selected_deploy_mode": deploy_mode,
        "final_execution_mode": template.get("execution_mode", "task"),
        "entrypoint": template.get("entrypoint", "run.sh"),
        "compatibility_badges": template.get("compatibility_badges", {}),
        "external_dependencies": template.get("external_dependencies", []),
        "uses_webagent": bool(template.get("uses_webagent")),
        "delegates_playwright": bool(template.get("delegates_playwright")),
        "warnings": _mode_conflicts(template, deploy_mode),
    }


def _read_requirements(workspace: Path) -> list[str]:
    req = workspace / "requirements.txt"
    if not req.exists():
        return []
    rows: list[str] = []
    for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        rows.append(item)
    return rows


def _snapshot_payload(agent: dict) -> dict[str, Any]:
    return {
        "selected_skills": agent.get("selected_skills", []),
        "skill_versions": (agent.get("flags") or {}).get("skill_versions", {}),
        "installed_requirements": _read_requirements(Path(agent["workspace_path"])),
        "runtime_flags": {
            "sandbox_mode": agent.get("sandbox_mode"),
            "network_access": agent.get("network_access"),
            "yolo_mode": agent.get("yolo_mode"),
        },
        "entrypoint": (agent.get("flags") or {}).get("entrypoint", "run.sh"),
    }


def _memory_context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    memory = payload.get("memory_context")
    if not isinstance(memory, dict):
        return {}
    content = str(memory.get("content") or "").strip()
    source = str(memory.get("source") or "none").strip() or "none"
    if not content:
        return {}
    return {"source": source, "content": content}


def _merge_system_prompt(system_prompt: str, memory_context: dict[str, Any]) -> str:
    content = str(memory_context.get("content") or "").strip()
    if not content:
        return system_prompt
    marker = "[CLUSTER MEMORY CONTEXT]"
    if marker in system_prompt:
        return system_prompt
    source = str(memory_context.get("source") or "unknown")
    prefix = (
        f"{marker}\\n"
        f"source: {source}\\n\\n"
        f"{content}\\n"
        f"[/CLUSTER MEMORY CONTEXT]\\n\\n"
    )
    return f"{prefix}{system_prompt}".strip()


def _run_check(agent: dict, command: str, check_type: str, request: Request) -> dict[str, Any]:
    workspace = Path(agent["workspace_path"])
    if not workspace.exists():
        raise HTTPException(status_code=400, detail="workspace does not exist; run prepare first")
    proc = subprocess.run(
        ["bash", "-lc", command],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    result = {
        "type": check_type,
        "command": command,
        "status": "passed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "output": output[-8000:],
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    request.app.state.log_service.append(
        agent["id"],
        None,
        "info" if proc.returncode == 0 else "error",
        f"{check_type} command={command} exit={proc.returncode}",
    )
    request.app.state.agent_manager.merge_flags(
        agent["id"],
        {f"last_{check_type}_result": result},
    )
    return result


@router.post("", response_model=AgentOut)
def create_agent(payload: dict, request: Request) -> AgentOut:
    manager = request.app.state.agent_manager
    memory_context = _memory_context_from_payload(payload)
    saved_prompts = dict(payload.get("saved_prompts") or {})
    system_prompt = str(saved_prompts.get("system") or "")
    if memory_context:
        saved_prompts["system"] = _merge_system_prompt(system_prompt, memory_context)
        payload["saved_prompts"] = saved_prompts
        flags = dict(payload.get("flags") or {})
        flags["memory_context"] = memory_context
        payload["flags"] = flags
    try:
        agent = manager.create_agent(AgentCreate(**payload))
        return AgentOut(**agent)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/from-template", response_model=AgentOut)
def create_agent_from_template(payload: dict, request: Request) -> AgentOut:
    template_slug = str(payload.get("template_slug") or "").strip()
    if not template_slug:
        raise HTTPException(status_code=400, detail="template_slug is required")
    template = request.app.state.starter_template_service.get_template(template_slug)
    if template is None:
        raise HTTPException(status_code=404, detail="starter template not found")

    deploy_mode = str(payload.get("deploy_mode") or template.get("recommended_deploy_mode") or "sandboxed").lower()
    mode = _deploy_mode_settings(deploy_mode)
    name = str(payload.get("name") or template.get("name") or template_slug)
    slug = str(payload.get("slug") or _slugify(name))
    description = str(payload.get("description") or template.get("description") or "")
    overrides = dict(payload.get("overrides") or {})
    template_saved_prompts = dict(template.get("saved_prompts") or {})
    if not template_saved_prompts and template.get("prompt_system"):
        template_saved_prompts = {"system": str(template.get("prompt_system") or "")}
    memory_context = _memory_context_from_payload(payload)
    if memory_context:
        template_saved_prompts["system"] = _merge_system_prompt(
            str(template_saved_prompts.get("system") or ""),
            memory_context,
        )
    override_saved_prompts = dict(overrides.get("saved_prompts") or {})
    flags = {
        "starter_template": {
            "slug": template["slug"],
            "pack_version": template.get("pack_version"),
            "template_version": template.get("template_version"),
            "source_zip": template.get("source_zip"),
        },
        "compatibility_badges": template.get("compatibility_badges", {}),
        "deploy_mode": deploy_mode,
        "entrypoint": template.get("entrypoint", "run.sh"),
        "dependencies_to_install": template.get("dependencies_to_install", []),
        "uses_webagent": bool(template.get("uses_webagent")),
        "delegates_playwright": bool(template.get("delegates_playwright")),
        "external_dependencies": template.get("external_dependencies", []),
        "validation_hook": template.get("validation_hook"),
        "smoke_test_command": template.get("smoke_test_command"),
        "mailbox_poll_seconds": int(payload.get("mailbox_poll_seconds") or 8),
    }
    if memory_context:
        flags["memory_context"] = memory_context
    payload_model = AgentCreate(
        name=name,
        slug=slug,
        description=description,
        agent_type=str(overrides.get("agent_type") or template.get("agent_type") or "specialized"),
        runtime=str(overrides.get("runtime") or template.get("runtime") or "python"),
        model_provider=overrides.get("model_provider", template.get("model_provider")),
        model_name=overrides.get("model_name", template.get("model_name")),
        selected_skills=list(overrides.get("selected_skills") or template.get("skills_to_attach", [])),
        flags={**flags, **dict(overrides.get("flags") or {})},
        role_identity=str(overrides.get("role_identity") or template.get("agent_type") or template_slug),
        specialization_mode=str(overrides.get("specialization_mode") or "custom"),
        domain_focus=str(overrides.get("domain_focus") or template.get("description") or ""),
        execution_mode=str(overrides.get("execution_mode") or template.get("execution_mode") or "task"),
        allowed_tools=list(overrides.get("allowed_tools") or []),
        runtime_policies=dict(overrides.get("runtime_policies") or template.get("runtime_flags") or {}),
        saved_prompts={**template_saved_prompts, **override_saved_prompts},
        specialization_metadata={
            "starter_template_slug": template["slug"],
            "uses_webagent": bool(template.get("uses_webagent")),
            "compatibility_badges": template.get("compatibility_badges", {}),
            "recommended_deploy_mode": template.get("recommended_deploy_mode"),
            "prompt_source_file": template.get("source_file"),
            "prompt_template_pack": template.get("pack_version"),
        },
        sandbox_mode=mode["sandbox_mode"],
        network_access=mode["network_access"],
        yolo_mode=mode["yolo_mode"],
    )
    try:
        created = request.app.state.agent_manager.create_agent(payload_model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentOut(**created)


@router.post("/preview-from-template")
def preview_agent_from_template(payload: dict, request: Request) -> dict:
    template_slug = str(payload.get("template_slug") or "").strip()
    if not template_slug:
        raise HTTPException(status_code=400, detail="template_slug is required")
    template = request.app.state.starter_template_service.get_template(template_slug)
    if template is None:
        raise HTTPException(status_code=404, detail="starter template not found")
    deploy_mode = str(payload.get("deploy_mode") or template.get("recommended_deploy_mode") or "sandboxed").lower()
    preview = _build_template_preview(template, deploy_mode)
    return {"template_slug": template_slug, "preview": preview}


@router.get("", response_model=list[AgentOut])
def list_agents(request: Request) -> list[AgentOut]:
    agents = request.app.state.agent_manager.list_agents()
    return [AgentOut(**a) for a in agents]


@router.delete("")
def delete_agents(request: Request) -> dict:
    return request.app.state.agent_manager.delete_all_agents()


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, request: Request) -> AgentOut:
    agent = _get_agent_or_404(request, agent_id)
    return AgentOut(**agent)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, payload: AgentUpdate, request: Request) -> AgentOut:
    try:
        agent = request.app.state.agent_manager.update_agent(agent_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentOut(**agent)


@router.post("/{agent_id}/skills")
def attach_skill(agent_id: str, payload: dict, request: Request) -> dict:
    skill_id = payload.get("skill_id")
    if not skill_id:
        raise HTTPException(status_code=400, detail="skill_id is required")
    manager = request.app.state.agent_manager
    if manager.get_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="skill not found")
    try:
        ok = manager.add_skill(agent_id, skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"agent_id": agent_id, "skill_id": skill_id, "attached": True}


@router.delete("/{agent_id}/skills/{skill_id}")
def detach_skill(agent_id: str, skill_id: str, request: Request) -> dict:
    ok = request.app.state.agent_manager.remove_skill(agent_id, skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="skill link not found")
    return {"agent_id": agent_id, "skill_id": skill_id, "removed": True}


@router.post("/{agent_id}/prepare", response_model=AgentActionResponse)
def prepare_agent(agent_id: str, request: Request) -> AgentActionResponse:
    manager = request.app.state.agent_manager
    workspace_service = request.app.state.workspace_service
    log_service = request.app.state.log_service
    agent = _get_agent_or_404(request, agent_id)

    manager.set_status(agent_id, "preparing", "prepare called")
    log_service.append(agent_id, None, "info", "prepare started")
    workspace_service.ensure_workspace(agent)
    request.app.state.mailbox_service.ensure_mailbox(agent)
    selected = set(agent.get("selected_skills", []))
    skills = [s for s in manager.list_skills() if s["id"] in selected]
    workspace_service.attach_skills(agent, skills)
    manifest_path = workspace_service.write_manifest(agent)
    ok, msg = workspace_service.install_requirements(agent)
    if not ok:
        manager.set_status(agent_id, "error", "prepare failed", last_error=msg)
        return AgentActionResponse(agent_id=agent_id, action="prepare", status="error", message=msg)

    manager.set_status(agent_id, "prepared", "prepare completed", last_error=None)
    return AgentActionResponse(
        agent_id=agent_id,
        action="prepare",
        status="prepared",
        message=f"prepare completed (manifest: {manifest_path})",
    )


@router.post("/{agent_id}/deploy", response_model=AgentActionResponse)
def deploy_agent(agent_id: str, request: Request) -> AgentActionResponse:
    manager = request.app.state.agent_manager
    workspace_service = request.app.state.workspace_service
    agent = _get_agent_or_404(request, agent_id)

    manager.set_status(agent_id, "deploying", "deploy called")
    workspace_service.ensure_workspace(agent)
    workspace_service.write_manifest(agent)
    snapshot = manager.create_snapshot(agent_id, _snapshot_payload(agent), reason="deploy")
    manager.set_status(agent_id, "deployed", "deploy completed")
    return AgentActionResponse(
        agent_id=agent_id,
        action="deploy",
        status="deployed",
        message=f"agent deployed snapshot={snapshot['id']}",
    )


@router.get("/{agent_id}/snapshots")
def get_agent_snapshots(
    agent_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    _get_agent_or_404(request, agent_id)
    snapshots = request.app.state.agent_manager.list_snapshots(agent_id, limit=limit)
    return {"agent_id": agent_id, "count": len(snapshots), "snapshots": snapshots}


@router.get("/{agent_id}/latest-snapshot")
def get_latest_agent_snapshot(agent_id: str, request: Request) -> dict:
    _get_agent_or_404(request, agent_id)
    latest = request.app.state.agent_manager.latest_snapshot(agent_id)
    return {"agent_id": agent_id, "snapshot": latest}


@router.post("/{agent_id}/run-validation")
def run_validation(agent_id: str, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    command = str((agent.get("flags") or {}).get("validation_hook") or "").strip()
    if not command:
        return {"agent_id": agent_id, "available": False, "message": "validation_hook not configured"}
    result = _run_check(agent, command, "validation", request)
    return {"agent_id": agent_id, "available": True, "result": result}


@router.post("/{agent_id}/run-smoke-test")
def run_smoke_test(agent_id: str, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    command = str((agent.get("flags") or {}).get("smoke_test_command") or "").strip()
    if not command:
        return {"agent_id": agent_id, "available": False, "message": "smoke_test_command not configured"}
    result = _run_check(agent, command, "smoke_test", request)
    return {"agent_id": agent_id, "available": True, "result": result}


@router.post("/{agent_id}/run", response_model=AgentActionResponse)
def run_agent(agent_id: str, payload: AgentRunRequest, request: Request) -> AgentActionResponse:
    run_service = request.app.state.run_service
    manager = request.app.state.agent_manager
    workspace_service = request.app.state.workspace_service
    agent = _get_agent_or_404(request, agent_id)
    if agent["status"] == "running":
        raise HTTPException(status_code=409, detail="agent already running")
    if payload.mailbox_poll_seconds:
        manager.merge_flags(agent_id, {"mailbox_poll_seconds": int(payload.mailbox_poll_seconds)})
    workspace_service.ensure_workspace(agent)
    request.app.state.mailbox_service.ensure_mailbox(agent)
    try:
        run_id, pid = run_service.start(agent, payload.command, payload.args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentActionResponse(
        agent_id=agent_id,
        action="run",
        status="running",
        message=f"run started pid={pid}",
        run_id=run_id,
    )


@router.get("/{agent_id}/mailbox/inbox")
def mailbox_inbox(
    agent_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    items = request.app.state.mailbox_service.list_box(agent, "inbox", limit=limit)
    return {"agent_id": agent_id, "mailbox": "inbox", "count": len(items), "items": items}


@router.get("/{agent_id}/mailbox/outbox")
def mailbox_outbox(
    agent_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    items = request.app.state.mailbox_service.list_box(agent, "outbox", limit=limit)
    return {"agent_id": agent_id, "mailbox": "outbox", "count": len(items), "items": items}


@router.post("/{agent_id}/mailbox/inbox")
def post_mailbox_inbox(agent_id: str, payload: AgentMailboxMessageCreate, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    item = request.app.state.mailbox_service.post_inbox(
        agent,
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
        metadata=payload.metadata,
    )
    request.app.state.log_service.append(agent_id, None, "info", f"mailbox inbox message queued id={item['id']}")
    return {"agent_id": agent_id, "item": item}


@router.post("/{agent_id}/mailbox/{message_id}/ack")
def ack_mailbox_inbox(agent_id: str, message_id: str, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    moved = request.app.state.mailbox_service.ack_inbox_message(agent, message_id)
    if moved is None:
        raise HTTPException(status_code=404, detail="inbox message not found")
    request.app.state.log_service.append(agent_id, None, "info", f"mailbox inbox message archived id={message_id}")
    return {"agent_id": agent_id, "archived": moved}


@router.post("/{agent_id}/dispatch")
def dispatch_agent_task(agent_id: str, payload: AgentDispatchRequest, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    request.app.state.workspace_service.ensure_workspace(agent)
    request.app.state.mailbox_service.ensure_mailbox(agent)
    metadata = dict(payload.metadata or {})
    if payload.command:
        metadata["command"] = payload.command
    item = request.app.state.mailbox_service.post_inbox(
        agent,
        sender=payload.sender,
        subject=payload.subject,
        body=payload.instruction,
        metadata=metadata,
    )
    request.app.state.log_service.append(agent_id, None, "info", f"dispatch queued message_id={item['id']}")
    started_run: dict[str, Any] | None = None
    if payload.auto_start and agent.get("status") != "running":
        run_id, pid = request.app.state.run_service.start(agent, None, None)
        started_run = {"run_id": run_id, "pid": pid}
    return {"agent_id": agent_id, "queued": item, "run_started": started_run}


@router.post("/{agent_id}/stop", response_model=AgentActionResponse)
def stop_agent(agent_id: str, request: Request) -> AgentActionResponse:
    run_service = request.app.state.run_service
    agent = _get_agent_or_404(request, agent_id)
    stopped = run_service.stop(agent)
    if not stopped:
        return AgentActionResponse(agent_id=agent_id, action="stop", status="noop", message="no active process")
    return AgentActionResponse(agent_id=agent_id, action="stop", status="stopped", message="agent stopped")


@router.get("/{agent_id}/logs")
def get_logs(
    agent_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=2000),
    run_id: str | None = Query(default=None),
) -> dict:
    _get_agent_or_404(request, agent_id)
    logs = request.app.state.log_service.get_logs(agent_id, limit=limit, run_id=run_id)
    return {"agent_id": agent_id, "count": len(logs), "logs": logs}


@router.get("/{agent_id}/status", response_model=AgentStatus)
def get_agent_status(agent_id: str, request: Request) -> AgentStatus:
    status = request.app.state.agent_manager.get_status(agent_id)
    if status is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentStatus(**status)


@router.get("/{agent_id}/workspace")
def get_workspace(agent_id: str, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    path = Path(agent["workspace_path"])
    return {
        "agent_id": agent_id,
        "workspace_path": str(path),
        "exists": path.exists(),
        "files": sorted([p.name for p in path.iterdir()]) if path.exists() else [],
    }


@router.get("/{agent_id}/manifest")
def get_manifest(agent_id: str, request: Request) -> dict:
    agent = _get_agent_or_404(request, agent_id)
    manifest = request.app.state.workspace_service.read_manifest(agent)
    return {"agent_id": agent_id, "manifest": manifest}
