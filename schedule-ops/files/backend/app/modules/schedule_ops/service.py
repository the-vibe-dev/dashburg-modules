from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.modules.orchestration.service import create_job, get_job, orchestration_job_to_payload, reconcile_jobs
from app.modules.remote_ops.runner_client import RunnerClientError
from app.modules.remote_ops.service import (
    _runner_client_for_node,
    get_node,
    get_nodes_health_status,
    list_nodes,
)


def list_schedule_nodes(session: Session) -> list[dict[str, Any]]:
    nodes = list_nodes(session)
    health = get_nodes_health_status(session)
    health_by_node = {
        str(item.get("node_id") or ""): item
        for item in (health.get("nodes") if isinstance(health, dict) else [])
        if isinstance(item, dict)
    }
    out: list[dict[str, Any]] = []
    for row in nodes:
        node_id = str(row.get("id") or "")
        item: dict[str, Any] = {
            "id": node_id,
            "label": str(row.get("label") or node_id),
            "enabled": bool(row.get("enabled", True)),
            "base_url": str(row.get("base_url") or ""),
            "supports_codex": bool(row.get("supports_codex", True)),
            "max_concurrent_jobs": int(row.get("max_concurrent_jobs") or 1),
            "health_status": str((health_by_node.get(node_id) or {}).get("status") or "unknown"),
            "health_ok": bool((health_by_node.get(node_id) or {}).get("ok", False)),
            "last_seen_at": row.get("last_seen_at"),
        }
        out.append(item)
    return out


def get_node_schedule(session: Session, node_id: str) -> dict[str, Any]:
    node = get_node(session, node_id)
    if not node:
        raise ValueError("node not found")
    return _runner_client_for_node(node).get_schedules()


def put_node_schedule(session: Session, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    node = get_node(session, node_id)
    if not node:
        raise ValueError("node not found")
    return _runner_client_for_node(node).put_schedules(payload)


def apply_node_schedule(session: Session, node_id: str) -> dict[str, Any]:
    node = get_node(session, node_id)
    if not node:
        raise ValueError("node not found")
    return _runner_client_for_node(node).apply_schedules()


def get_node_schedule_status(session: Session, node_id: str) -> dict[str, Any]:
    node = get_node(session, node_id)
    if not node:
        raise ValueError("node not found")
    status = _runner_client_for_node(node).get_schedules_status()
    status["node"] = {
        "id": node.id,
        "label": node.label,
        "enabled": bool(node.enabled),
        "base_url": node.base_url,
        "supports_codex": bool(node.supports_codex),
        "max_concurrent_jobs": int(node.max_concurrent_jobs or 1),
        "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
    }
    return status


def list_schedule_status(session: Session) -> dict[str, Any]:
    nodes = list_nodes(session)
    health = get_nodes_health_status(session)
    health_by_node = {
        str(item.get("node_id") or ""): item
        for item in (health.get("nodes") if isinstance(health, dict) else [])
        if isinstance(item, dict)
    }
    items: list[dict[str, Any]] = []
    for row in nodes:
        node_id = str(row.get("id") or "")
        health_row = health_by_node.get(node_id) or {}
        node_payload = {
            "id": node_id,
            "label": str(row.get("label") or node_id),
            "enabled": bool(row.get("enabled", True)),
            "base_url": str(row.get("base_url") or ""),
            "supports_codex": bool(row.get("supports_codex", True)),
            "max_concurrent_jobs": int(row.get("max_concurrent_jobs") or 1),
            "health_status": str(health_row.get("status") or "unknown"),
            "health_ok": bool(health_row.get("ok", False)),
            "last_seen_at": row.get("last_seen_at"),
        }
        node = get_node(session, node_id)
        if not node:
            items.append(
                {
                    "node": node_payload,
                    "node_id": node_id,
                    "generated_at": None,
                    "config_updated_at": None,
                    "install": {"path": "/etc/cron.d/dashburg-runner-scheduleops", "installed": False},
                    "entries": [],
                    "error": "node not found",
                }
            )
            continue
        try:
            status = _runner_client_for_node(node).get_schedules_status()
            status["node"] = node_payload
            items.append(status)
        except Exception as exc:
            items.append(
                {
                    "node": node_payload,
                    "node_id": node_id,
                    "generated_at": None,
                    "config_updated_at": None,
                    "install": {"path": "/etc/cron.d/dashburg-runner-scheduleops", "installed": False},
                    "entries": [],
                    "error": str(exc),
                }
            )
    return {"items": items}


def _first_allowed_repo(node_row: dict[str, Any]) -> str:
    allowed = node_row.get("allowed_repos") if isinstance(node_row.get("allowed_repos"), list) else []
    for row in allowed:
        value = str(row).strip()
        if value:
            return value
    return ""


def create_diagnostic_delegate(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    node_id = str(payload.get("node_id") or "").strip()
    issue = str(payload.get("issue") or "").strip()
    if not node_id:
        raise ValueError("node_id is required")
    if not issue:
        raise ValueError("issue is required")
    node = get_node(session, node_id)
    if not node:
        raise ValueError("node not found")

    node_rows = list_nodes(session)
    node_row = next((row for row in node_rows if str(row.get("id") or "") == node_id), {})
    repo_path = str(payload.get("repo_path") or "").strip() or _first_allowed_repo(node_row)
    workspace_path = str(payload.get("workspace_path") or "").strip() or repo_path
    if not repo_path:
        raise ValueError("repo_path is required for this node")

    title = str(payload.get("title") or f"Diagnostic: {issue[:96]}").strip()
    prompt = (
        "Investigate the following issue on this node using node-local execution. "
        "Use mailbox/knowledge context when relevant and provide actionable next steps.\n\n"
        f"Issue:\n{issue}\n\n"
        "Execution rules:\n"
        "- Prefer orchestration mailbox and local artifacts over brittle ad-hoc SSH transcripts.\n"
        "- If you plan large repo mutations, create an NFS backup before edits.\n"
        "- Return concise findings, changed files, and next actions.\n"
    )
    instructions = str(payload.get("instructions") or "").strip() or (
        "Delegated node diagnostic from ScheduleOps. Complete diagnostics and report via structured result + mailbox events."
    )
    mode = str(payload.get("codex_mode") or "workspace-write").strip().lower()
    if mode not in {"read-only", "workspace-write", "danger-full-access"}:
        mode = "workspace-write"
    timeout_seconds = int(payload.get("timeout_seconds") or 5400)
    timeout_seconds = max(60, min(timeout_seconds, 86400))

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    row = create_job(
        session,
        {
            "title": title,
            "task_type": "node_diagnostic",
            "target_node": node_id,
            "repo_path": repo_path,
            "workspace_path": workspace_path,
            "prompt": prompt,
            "instructions": instructions,
            "execution_mode": "delegated_runner",
            "codex_mode": mode,
            "priority": int(payload.get("priority") or 90),
            "timeout_seconds": timeout_seconds,
            "max_retries": int(payload.get("max_retries") or 1),
            "metadata": {
                **metadata,
                "requested_by": "schedule_ops",
                "issue": issue,
                "schedule_ops": True,
                "require_nfs_backup": True,
            },
        },
    )
    reconcile_jobs(session)
    fresh = get_job(session, row.id) or row
    return orchestration_job_to_payload(fresh)


def map_runner_error(exc: Exception) -> tuple[int, Any]:
    if isinstance(exc, RunnerClientError):
        return exc.status, exc.detail
    if isinstance(exc, ValueError):
        return 404, str(exc)
    return 500, str(exc)
