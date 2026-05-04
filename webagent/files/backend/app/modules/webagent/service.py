from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import HTTPException
from sqlmodel import Session, select

from app.modules.webagent.constants import (
    PLAYWRIGHT_ACTION_ALIASES,
    PLAYWRIGHT_ACTIONS,
    SESSION_OPTIONAL_ACTIONS,
    TOOL_TO_ACTION,
    WEBAGENT_RUN_TYPE_ALIASES,
    WEBAGENT_RUN_TYPES,
)
from app.modules.webagent.config import drop_connection_overrides, redact_sensitive, resolve_webagent_bridge_config
from app.modules.webagent.deep_explore import build_deep_explore_plan
from app.modules.webagent.fake_assets import create_test_asset
from app.modules.webagent.form_profiles import classify_field, persona_from_seed, value_for_class
from app.modules.webagent.reporting import build_markdown_report, build_machine_report
from app.modules.webagent.safety import detect_destructive_action, scrub_secrets
from app.modules.webagent.settings import normalize_settings
from app.models.remoteops import RemoteOpsNode
from app.models.webagent import WebAgentReport, WebAgentRun
from app.modules.remote_ops.service import (
    RemoteOpsError,
    create_remote_job,
    fetch_remote_artifact_content,
    fetch_remote_artifacts,
    fetch_remote_logs,
    get_node,
    get_node_health_status,
    get_remote_job,
    job_to_payload,
    sync_remote_job_status,
)

WEBAGENT_PUBLIC_RUN_TYPES = set(WEBAGENT_RUN_TYPES) | set(WEBAGENT_RUN_TYPE_ALIASES.keys())
WEBAGENT_PLAYWRIGHT_ACTIONS = PLAYWRIGHT_ACTIONS

# Transport-level canonical run types currently expected by many webagent nodes.
_TRANSPORT_RUN_TYPE_MAP: dict[str, str] = {
    "browse": "web-explorer",
    "test": "web-test",
    "form-fill": "web-test",
    "upload-test": "web-test",
    "deep-explore": "web-explorer",
    "qa-audit": "web-test",
    "autonomous-task": "web-explorer",
    "extraction-only": "scrape",
}


def _now() -> datetime:
    return datetime.utcnow()


def _jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _jloads_dict(value: str) -> dict[str, Any]:
    try:
        raw = json.loads(value or "{}")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _jloads_list(value: str) -> list[Any]:
    try:
        raw = json.loads(value or "[]")
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _normalize_target_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="target_url is required")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="target_url must be an absolute http(s) URL")
    return raw


def _normalize_run_type(run_type: str) -> str:
    value = str(run_type or "").strip().lower()
    if value in WEBAGENT_RUN_TYPE_ALIASES:
        value = WEBAGENT_RUN_TYPE_ALIASES[value]
    if value in WEBAGENT_RUN_TYPES:
        return _TRANSPORT_RUN_TYPE_MAP.get(value, value)
    raise HTTPException(status_code=400, detail=f"run_type must be one of {sorted(WEBAGENT_PUBLIC_RUN_TYPES)}")


def _default_node_id() -> str:
    return str(os.getenv("WEBAGENT_NODE_ID", "webagent")).strip() or "webagent"


def resolve_webagent_node(session: Session, requested_node_id: str | None = None) -> RemoteOpsNode:
    rid = str(requested_node_id or "").strip()
    if rid:
        node = get_node(session, rid)
        if not node:
            raise HTTPException(status_code=404, detail=f"node not found: {rid}")
        return node

    preferred = _default_node_id()
    by_id = get_node(session, preferred)
    if by_id:
        return by_id

    nodes = session.exec(select(RemoteOpsNode).order_by(RemoteOpsNode.label.asc())).all()
    for node in nodes:
        label = str(node.label or "").lower()
        node_id = str(node.id or "").lower()
        if "webagent" in label or "web-agent" in label or node_id == "webagent":
            return node
    raise HTTPException(status_code=404, detail="webagent node not found; set WEBAGENT_NODE_ID or add a node named webagent")


def _normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    return normalize_settings(raw)


def _artifacts(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("artifacts")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _artifact_path(row: dict[str, Any]) -> str:
    return str(row.get("local_rel_path") or row.get("path") or "").strip()


def _artifact_groups(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped = result.get("artifacts_by_type")
    if isinstance(grouped, dict):
        out: dict[str, list[dict[str, Any]]] = {}
        for key, value in grouped.items():
            if isinstance(value, list):
                out[str(key)] = [row for row in value if isinstance(row, dict)]
        if out:
            return out
    buckets: dict[str, list[dict[str, Any]]] = {
        "screenshots": [],
        "videos": [],
        "traces": [],
        "logs": [],
        "generated_tests": [],
        "discovery": [],
        "other": [],
    }
    for row in _artifacts(result):
        path = _artifact_path(row).lower()
        if not path:
            continue
        if path.endswith((".png", ".jpg", ".jpeg", ".webp")):
            buckets["screenshots"].append(row)
        elif path.endswith((".webm", ".mp4")):
            buckets["videos"].append(row)
        elif path.endswith("trace.zip"):
            buckets["traces"].append(row)
        elif path.endswith(".log"):
            buckets["logs"].append(row)
        elif "generated_tests/" in path or path.endswith(".spec.ts"):
            buckets["generated_tests"].append(row)
        elif path.endswith(".json"):
            buckets["discovery"].append(row)
        else:
            buckets["other"].append(row)
    return buckets


def _infer_artifact_manifest(result: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = result.get("artifact_manifest")
    if isinstance(manifest, list):
        return [m for m in manifest if isinstance(m, dict)]
    grouped = _artifact_groups(result)
    return [{"key": key, "count": len(rows)} for key, rows in grouped.items() if rows]


def _summarize_result(target_url: str, run_type: str, result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    routes = report.get("sitemap") if isinstance(report.get("sitemap"), list) else []
    forms = result.get("forms") if isinstance(result.get("forms"), list) else []
    buttons = result.get("buttons") if isinstance(result.get("buttons"), list) else []
    discovered_pages = report.get("discoveredPages") if isinstance(report.get("discoveredPages"), list) else []
    if not discovered_pages:
        discovered_pages = result.get("discoveredPages") if isinstance(result.get("discoveredPages"), list) else []
    if not routes:
        routes = report.get("sitemap") if isinstance(report.get("sitemap"), list) else []
    if not routes and discovered_pages:
        routes = [
            {"url": str(page.get("url") or ""), "title": str(page.get("title") or "")}
            for page in discovered_pages
            if isinstance(page, dict) and str(page.get("url") or "").strip()
        ]
    if not forms and discovered_pages:
        forms = []
        for page in discovered_pages:
            if not isinstance(page, dict):
                continue
            page_forms = page.get("forms")
            if not isinstance(page_forms, list):
                continue
            for f in page_forms:
                if isinstance(f, dict):
                    forms.append(f)
    if not buttons and discovered_pages:
        buttons = []
        for page in discovered_pages:
            if not isinstance(page, dict):
                continue
            page_buttons = page.get("buttons")
            if not isinstance(page_buttons, list):
                continue
            for b in page_buttons:
                if isinstance(b, dict):
                    buttons.append(b)
    api_eps = report.get("apiEndpoints") if isinstance(report.get("apiEndpoints"), list) else []
    js_eps = report.get("jsEndpoints") if isinstance(report.get("jsEndpoints"), list) else []
    grouped = _artifact_groups(result)
    screenshots = grouped.get("screenshots", [])
    generated_tests = grouped.get("generated_tests", [])
    auth_surfaces = [item for item in forms if isinstance(item, dict) and any("pass" in str(v).lower() for v in item.values())]
    summary_text = str(result.get("summary") or report.get("summary") or "").strip()
    if not summary_text:
        summary_text = f"Run `{run_type}` completed for {target_url}."
    return {
        "summary_text": summary_text,
        "what_this_page_appears_to_be": str(result.get("page_type") or "Not inferred"),
        "main_flows_detected": [str(v) for v in (result.get("flows") if isinstance(result.get("flows"), list) else [])[:10]],
        "potential_auth_surfaces": auth_surfaces[:20],
        "important_forms_and_actions": forms[:25],
        "interesting_api_endpoints": api_eps[:25],
        "interesting_js_endpoints": js_eps[:25],
        "usability_concerns": [str(v) for v in (result.get("ux_concerns") if isinstance(result.get("ux_concerns"), list) else [])[:15]],
        "suggested_next_run_types": [t for t in WEBAGENT_RUN_TYPES if t != run_type][:4],
        "counts": {
            "routes": len(routes),
            "forms": len(forms),
            "buttons": len(buttons),
            "api_endpoints": len(api_eps),
            "js_endpoints": len(js_eps),
            "screenshots": len(screenshots),
            "generated_tests": len(generated_tests),
        },
        "warnings": [str(v) for v in (result.get("warnings") if isinstance(result.get("warnings"), list) else [])[:50]],
        "errors": [str(v) for v in (result.get("errors") if isinstance(result.get("errors"), list) else [])[:50]],
    }


def _row_payload(row: WebAgentRun) -> dict[str, Any]:
    settings = _jloads_dict(row.settings_json)
    result = _jloads_dict(row.result_json)
    grouped = _artifact_groups(result)
    live = result.get("live_session") if isinstance(result.get("live_session"), dict) else {}
    replay = result.get("replay") if isinstance(result.get("replay"), dict) else {}
    return {
        "id": row.id,
        "target_url": row.target_url,
        "run_type": row.run_type,
        "node_id": row.node_id,
        "remote_job_id": row.remote_job_id,
        "status": row.status,
        "settings": settings,
        "summary": _jloads_dict(row.summary_json),
        "artifact_manifest": _jloads_list(row.artifact_manifest_json),
        "result": result,
        "live_session": {
            "enabled": bool(settings.get("enable_live_view", False)),
            "status": str(live.get("status") or ("active" if row.status == "running" and settings.get("enable_live_view") else "disabled")),
            "url": str(live.get("url") or ""),
        },
        "replay": {
            "trace_available": bool(replay.get("trace_available", len(grouped.get("traces", [])) > 0)),
            "video_available": bool(replay.get("video_available", len(grouped.get("videos", [])) > 0)),
        },
        "artifact_counts": {key: len(value) for key, value in grouped.items()},
        "error_message": row.error_message,
        "notes": row.notes,
        "created_by": row.created_by,
        "is_saved": row.is_saved,
        "is_useful": row.is_useful,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _sync_from_remote_job(session: Session, row: WebAgentRun) -> tuple[WebAgentRun, dict[str, Any]]:
    detail_payload: dict[str, Any] = {}
    if not row.remote_job_id:
        return row, detail_payload
    remote = get_remote_job(session, row.remote_job_id)
    if not remote:
        row.status = "failed"
        row.error_message = "remote job not found"
        row.updated_at = _now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return row, detail_payload

    remote, runner_detail = sync_remote_job_status(session, remote)
    logs_tail = fetch_remote_logs(session, remote, max_lines=400)
    artifact_snapshot = fetch_remote_artifacts(session, remote)
    detail_payload = job_to_payload(remote)
    detail_payload["runner_detail"] = runner_detail
    detail_payload["logs_tail"] = logs_tail
    detail_payload["artifacts"] = artifact_snapshot
    detail_payload = redact_sensitive(detail_payload)

    row.status = remote.status
    if row.started_at is None and row.status in {"running", "completed", "failed", "cancelled"}:
        row.started_at = remote.created_at
    if row.status in {"completed", "failed", "cancelled"} and row.completed_at is None:
        row.completed_at = remote.finished_at or _now()

    runner_result = runner_detail.get("result") if isinstance(runner_detail, dict) else {}
    runner_result = runner_result if isinstance(runner_result, dict) else {}
    runner_result = redact_sensitive(runner_result)
    artifact_items = artifact_snapshot.get("items") if isinstance(artifact_snapshot, dict) else None
    if isinstance(artifact_items, list) and artifact_items:
        normalized_items = [item for item in artifact_items if isinstance(item, dict)]
        if not isinstance(runner_result.get("artifacts"), list):
            runner_result["artifacts"] = normalized_items
        runner_result.setdefault("artifact_manifest", [{"key": "artifacts", "count": len(normalized_items)}])

    artifact_manifest = _infer_artifact_manifest(runner_result)
    summary = _summarize_result(row.target_url, row.run_type, runner_result)
    error_message = ""
    if row.status == "failed":
        error_message = str(runner_result.get("error") or runner_detail.get("error") or "run failed")

    row.result_json = _jdumps(runner_result)
    row.summary_json = _jdumps(summary)
    row.artifact_manifest_json = _jdumps(artifact_manifest)
    row.error_message = error_message
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, detail_payload


def create_webagent_run(
    session: Session,
    *,
    target_url: str,
    run_type: str,
    node_id: str | None = None,
    settings: dict[str, Any] | None = None,
    notes: str = "",
    created_by: str = "ui",
) -> dict[str, Any]:
    norm_url = _normalize_target_url(target_url)
    requested_type = str(run_type or "").strip().lower()
    norm_type = _normalize_run_type(requested_type)
    norm_settings = _normalize_settings({**(settings or {}), "run_type": norm_type, "requested_run_type": requested_type})
    node = resolve_webagent_node(session, node_id)
    bridge_cfg = resolve_webagent_bridge_config(node)
    job_params = {
        "target_url": norm_url,
        "run_type": norm_type,
        "options": norm_settings,
        "notes": str(notes or "").strip(),
        **(bridge_cfg.get("dispatch_params") if isinstance(bridge_cfg, dict) else {}),
    }
    remote_job = create_remote_job(session, node=node, job_type="webagent.run", params=job_params, created_by=created_by)
    now = _now()
    row = WebAgentRun(
        id=uuid.uuid4().hex,
        target_url=norm_url,
        run_type=norm_type,
        node_id=node.id,
        remote_job_id=remote_job.id,
        status=remote_job.status,
        settings_json=_jdumps(norm_settings),
        notes=str(notes or "").strip(),
        created_by=created_by,
        started_at=now if remote_job.status == "running" else None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _row_payload(row)


def _normalize_action(action: str) -> str:
    raw = str(action or "").strip().lower().replace("-", "_")
    value = PLAYWRIGHT_ACTION_ALIASES.get(raw, raw)
    if value not in WEBAGENT_PLAYWRIGHT_ACTIONS:
        raise HTTPException(status_code=400, detail=f"unsupported action; expected one of {sorted(WEBAGENT_PLAYWRIGHT_ACTIONS)}")
    return value


def _wait_for_remote_job(session: Session, remote_job_id: str, timeout_seconds: int = 90, poll_interval_seconds: float = 1.0) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.time() + max(5, int(timeout_seconds))
    last_detail: dict[str, Any] = {}
    while time.time() < deadline:
        row = get_remote_job(session, remote_job_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"remote job not found: {remote_job_id}")
        row, detail = sync_remote_job_status(session, row)
        last_detail = detail if isinstance(detail, dict) else {}
        if row.status in {"completed", "failed", "cancelled"}:
            payload = job_to_payload(row)
            return payload, last_detail
        time.sleep(max(0.2, poll_interval_seconds))
    raise HTTPException(status_code=504, detail=f"remote action timed out after {timeout_seconds}s")


def execute_webagent_action(
    session: Session,
    *,
    action: str,
    node_id: str | None = None,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    node = resolve_webagent_node(session, node_id)
    bridge_cfg = resolve_webagent_bridge_config(node)
    normalized = _normalize_action(action)
    sid = str(session_id or "").strip()
    params = drop_connection_overrides(payload)
    if normalized not in SESSION_OPTIONAL_ACTIONS and not sid:
        raise HTTPException(status_code=400, detail="session_id is required for this action")
    safety = params.get("safety") if isinstance(params.get("safety"), dict) else {}
    allow_destructive = bool(safety.get("allow_destructive", False))
    if normalized in {"click", "press", "fill", "check", "uncheck", "select_option"} and not allow_destructive:
        destructive = detect_destructive_action(
            label=str(params.get("label") or ""),
            text=str(params.get("text") or params.get("value") or ""),
            selector=str(params.get("selector") or ""),
        )
        if destructive["is_destructive"]:
            raise HTTPException(
                status_code=400,
                detail=f"blocked potentially destructive action; keywords={destructive['keywords']}",
            )
    if bool(safety.get("scrub_secrets", True)):
        params = scrub_secrets(params)

    job_params = {
        "action": normalized,
        "session_id": sid,
        "timeout_seconds": int(timeout_seconds),
        **params,
        **(bridge_cfg.get("dispatch_params") if isinstance(bridge_cfg, dict) else {}),
    }
    try:
        remote_job = create_remote_job(session, node=node, job_type="webagent.action", params=job_params, created_by="webagent-api")
    except RemoteOpsError as exc:
        detail = exc.detail if isinstance(exc.detail, (dict, list, str)) else {"detail": str(exc.detail)}
        raise HTTPException(status_code=502, detail=detail) from exc
    job, detail = _wait_for_remote_job(session, remote_job.id, timeout_seconds=timeout_seconds)
    result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
    status = str(job.get("status", "")).lower()
    if status != "completed":
        err = result.get("error") or detail.get("error") or f"action failed with status={status}"
        raise HTTPException(status_code=502, detail=str(err))
    return {
        "ok": True,
        "node_id": node.id,
        "action": normalized,
        "session_id": str(result.get("session_id") or sid),
        "job": job,
        "result": result,
    }


def execute_webagent_tool(
    session: Session,
    *,
    tool_name: str,
    node_id: str | None = None,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    normalized_tool = str(tool_name or "").strip().lower().replace("-", "_")
    if not normalized_tool:
        raise HTTPException(status_code=400, detail="tool_name is required")

    body = drop_connection_overrides(payload)
    if normalized_tool == "generate_test_asset":
        output_dir = str(body.get("output_dir") or "/tmp/dashburg-webagent-assets")
        kind = str(body.get("kind") or "text")
        name = str(body.get("name") or f"{kind}-asset")
        created = create_test_asset(
            output_dir=output_dir,
            kind=kind,
            name=name,
            content=(str(body.get("content")) if body.get("content") is not None else None),
            target_size_bytes=(int(body["target_size_bytes"]) if body.get("target_size_bytes") is not None else None),
            rows=int(body.get("rows") or 10),
        )
        return {"ok": True, "tool": normalized_tool, "result": created}

    if normalized_tool == "deep_explore_page":
        items = body.get("items") if isinstance(body.get("items"), list) else []
        aggression = str(body.get("aggression") or "normal")
        allow_destructive = bool(body.get("allow_destructive", False))
        max_actions = int(body.get("max_actions", 200) or 200)
        plan = build_deep_explore_plan(
            items=[item for item in items if isinstance(item, dict)],
            aggression=aggression,
            allow_destructive=allow_destructive,
            max_actions=max_actions,
        )
        return {"ok": True, "tool": normalized_tool, "result": plan}

    if normalized_tool == "fill_form":
        fields = body.get("fields") if isinstance(body.get("fields"), list) else []
        mode = str(body.get("fill_mode") or "realistic")
        seed = int(body.get("seed") or 7)
        persona = persona_from_seed(seed)
        rows: list[dict[str, Any]] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or field.get("label") or "")
            fclass = classify_field(name)
            rows.append(
                {
                    "name": name,
                    "selector": field.get("selector"),
                    "field_class": fclass,
                    "value": value_for_class(fclass, persona, mode=mode),
                }
            )
        return {"ok": True, "tool": normalized_tool, "result": {"mode": mode, "seed": seed, "fills": rows}}

    if normalized_tool in {"analyze_failures", "summarize_run"}:
        warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
        errors = body.get("errors") if isinstance(body.get("errors"), list) else []
        base = {
            "summary_text": str(body.get("summary_text") or body.get("summary") or ""),
            "status": str(body.get("status") or "unknown"),
            "counts": body.get("counts") if isinstance(body.get("counts"), dict) else {},
            "warnings": [str(v) for v in warnings],
            "errors": [str(v) for v in errors],
        }
        return {
            "ok": True,
            "tool": normalized_tool,
            "result": {
                "machine_report": build_machine_report(base),
                "markdown_report": build_markdown_report(base),
            },
        }

    action = TOOL_TO_ACTION.get(normalized_tool, normalized_tool)
    return execute_webagent_action(
        session,
        action=action,
        node_id=node_id,
        session_id=session_id,
        payload=body,
        timeout_seconds=timeout_seconds,
    )


def list_webagent_runs(session: Session, *, status: str | None = None, saved_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(WebAgentRun).order_by(WebAgentRun.created_at.desc()).limit(max(1, min(500, int(limit))))
    rows = list(session.exec(stmt).all())
    out: list[dict[str, Any]] = []
    for row in rows:
        if status and row.status != status:
            continue
        if saved_only and not row.is_saved:
            continue
        out.append(_row_payload(row))
    return out


def get_webagent_run_detail(session: Session, run_id: str) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    row, detail_payload = _sync_from_remote_job(session, row)
    payload = _row_payload(row)
    payload["remote"] = detail_payload
    payload["logs"] = (detail_payload.get("logs_tail") if isinstance(detail_payload, dict) else {}) or {"offset": 0, "lines": []}
    return payload


def get_webagent_run_logs(session: Session, run_id: str, limit: int = 400) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    row, detail_payload = _sync_from_remote_job(session, row)
    logs = (detail_payload.get("logs_tail") if isinstance(detail_payload, dict) else {}) or {"offset": 0, "lines": []}
    lines = logs.get("lines") if isinstance(logs, dict) else []
    if not isinstance(lines, list):
        lines = []
    return {
        "run_id": row.id,
        "status": row.status,
        "offset": int(logs.get("offset", 0) if isinstance(logs, dict) else 0),
        "lines": [str(line) for line in lines][-max(1, min(2000, int(limit))) :],
    }


def get_webagent_run_artifacts(session: Session, run_id: str) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    row, detail_payload = _sync_from_remote_job(session, row)
    result = _jloads_dict(row.result_json)
    grouped = _artifact_groups(result)
    items = _artifacts(result)
    remote_artifacts = detail_payload.get("artifacts") if isinstance(detail_payload, dict) else {}
    return {
        "run_id": row.id,
        "status": row.status,
        "items": items,
        "groups": grouped,
        "artifact_root": str((remote_artifacts or {}).get("artifact_root") or ""),
    }


def get_webagent_run_replay_assets(session: Session, run_id: str) -> dict[str, Any]:
    artifacts = get_webagent_run_artifacts(session, run_id)
    groups = artifacts.get("groups") if isinstance(artifacts.get("groups"), dict) else {}
    videos = groups.get("videos") if isinstance(groups.get("videos"), list) else []
    traces = groups.get("traces") if isinstance(groups.get("traces"), list) else []
    videos_sorted = sorted(
        [v for v in videos if isinstance(v, dict)],
        key=lambda row: int(row.get("size_bytes") or 0),
        reverse=True,
    )
    return {
        "run_id": run_id,
        "video_available": len(videos_sorted) > 0,
        "trace_available": len(traces) > 0,
        "primary_video": videos_sorted[0] if videos_sorted else None,
        "videos": videos_sorted,
        "traces": traces,
    }


def get_webagent_run_screenshots(session: Session, run_id: str) -> dict[str, Any]:
    artifacts = get_webagent_run_artifacts(session, run_id)
    groups = artifacts.get("groups") if isinstance(artifacts.get("groups"), dict) else {}
    rows = groups.get("screenshots") if isinstance(groups.get("screenshots"), list) else []
    return {"run_id": run_id, "items": rows, "count": len(rows)}


def get_webagent_generated_tests(session: Session, run_id: str) -> dict[str, Any]:
    artifacts = get_webagent_run_artifacts(session, run_id)
    groups = artifacts.get("groups") if isinstance(artifacts.get("groups"), dict) else {}
    rows = groups.get("generated_tests") if isinstance(groups.get("generated_tests"), list) else []
    return {"run_id": run_id, "items": rows, "count": len(rows)}


def get_webagent_discovery(session: Session, run_id: str) -> dict[str, Any]:
    detail = get_webagent_run_detail(session, run_id)
    result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    return {
        "run_id": run_id,
        "sitemap": report.get("sitemap", []),
        "forms": report.get("forms", result.get("forms", [])),
        "login_surfaces": report.get("loginSurfaces", []),
        "buttons": report.get("buttons", result.get("buttons", [])),
        "api_endpoints": report.get("apiEndpoints", result.get("api_endpoints", [])),
        "js_endpoints": report.get("jsEndpoints", result.get("js_endpoints", [])),
        "ux_score": report.get("uxScore"),
        "lighthouse": report.get("lighthouse", result.get("lighthouse", {})),
        "report": report,
    }


def get_webagent_live_session(session: Session, run_id: str) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    row, _ = _sync_from_remote_job(session, row)
    settings = _jloads_dict(row.settings_json)
    result = _jloads_dict(row.result_json)
    live = result.get("live_session") if isinstance(result.get("live_session"), dict) else {}
    enabled = bool(settings.get("enable_live_view", False))
    status = str(live.get("status") or ("active" if row.status == "running" and enabled else ("ended" if enabled else "disabled")))
    raw_url = str(live.get("url") or "")
    if raw_url:
        try:
            parsed = urlparse(raw_url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault("autoconnect", "1")
            query.setdefault("resize", "scale")
            query.setdefault("view_clip", "1")
            query.setdefault("quality", "9")
            raw_url = urlunparse(parsed._replace(query=urlencode(query)))
        except Exception:
            pass
    return {
        "run_id": run_id,
        "enabled": enabled,
        "status": status,
        "url": raw_url,
        "message": str(live.get("message") or ("Live session uses rolling screenshots/logs for this run." if enabled else "Live view disabled for this run.")),
    }


def get_webagent_artifact_content(session: Session, run_id: str, artifact_path: str) -> bytes:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    remote = get_remote_job(session, row.remote_job_id)
    if not remote:
        raise HTTPException(status_code=404, detail="remote job not found")
    content, error = fetch_remote_artifact_content(session, remote, artifact_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"artifact unavailable: {error or 'not found'}")
    return content


def retry_webagent_run(session: Session, run_id: str) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    return create_webagent_run(
        session,
        target_url=row.target_url,
        run_type=row.run_type,
        node_id=row.node_id,
        settings=_jloads_dict(row.settings_json),
        notes=row.notes,
        created_by="retry",
    )


def mark_webagent_run_useful(session: Session, run_id: str, is_useful: bool) -> dict[str, Any]:
    row = session.get(WebAgentRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="webagent run not found")
    row.is_useful = bool(is_useful)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _row_payload(row)


def save_webagent_report(session: Session, run_id: str, title: str = "") -> dict[str, Any]:
    detail = get_webagent_run_detail(session, run_id)
    row = session.get(WebAgentRun, run_id)
    assert row is not None
    summary = detail.get("summary", {})
    summary_text = str(summary.get("summary_text") or f"WebAgent report for {row.target_url}")
    report = WebAgentReport(
        id=uuid.uuid4().hex,
        run_id=row.id,
        title=str(title or "").strip() or f"{row.run_type} · {row.target_url}",
        summary_markdown=summary_text,
        payload_json=_jdumps(detail),
        created_at=_now(),
    )
    session.add(report)
    row.is_saved = True
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(report)
    session.refresh(row)
    return {
        "id": report.id,
        "run_id": report.run_id,
        "title": report.title,
        "summary_markdown": report.summary_markdown,
        "payload": _jloads_dict(report.payload_json),
        "created_at": report.created_at,
    }


def list_webagent_reports(session: Session, limit: int = 200) -> list[dict[str, Any]]:
    rows = session.exec(select(WebAgentReport).order_by(WebAgentReport.created_at.desc()).limit(max(1, min(500, int(limit))))).all()
    return [
        {
            "id": row.id,
            "run_id": row.run_id,
            "title": row.title,
            "summary_markdown": row.summary_markdown,
            "payload": _jloads_dict(row.payload_json),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def webagent_status(session: Session, requested_node_id: str | None = None) -> dict[str, Any]:
    node = resolve_webagent_node(session, requested_node_id)
    health = get_node_health_status(session, node)
    bridge_cfg = resolve_webagent_bridge_config(node)
    diagnostics = bridge_cfg.get("diagnostics", {}) if isinstance(bridge_cfg, dict) else {}
    allowed_job_types = [str(v) for v in _jloads_list(node.allowed_job_types_json) if str(v).strip()]
    allowlist_empty = len(allowed_job_types) == 0
    # Many deployed runners leave allowed_job_types empty to mean "allow all".
    # Treat an empty list as unknown/allow-all, and only disable interactive mode when
    # an explicit allowlist is present that omits webagent.action/webagent.run.
    interactive_supported = allowlist_empty or "webagent.action" in allowed_job_types or "webagent.run" in allowed_job_types
    capabilities = [
        "scraping",
        "discovery",
        "web exploration",
        "artifact generation",
        "ux/performance analysis",
        "live session",
        "replay",
        "deep-explore planning with destructive-action guardrails",
        "form-fill profiles with deterministic test personas",
        "upload testing helpers and fake test asset generation",
        "machine-readable and markdown report generation",
    ]
    if interactive_supported:
        capabilities.extend(
            [
                "playwright interactive sessions",
                "playwright click/fill/select/check/upload/drag/hover/focus",
                "playwright keyboard/mouse/wait/screenshot/evaluate/extract/pdf",
            ]
        )
    setup = {
        "configured": bool(diagnostics.get("configured", False)),
        "issues": diagnostics.get("issues", []) if isinstance(diagnostics.get("issues"), list) else [],
        "runner_webagent_run_allowed": allowlist_empty or "webagent.run" in allowed_job_types,
        "runner_webagent_action_allowed": interactive_supported,
    }
    return {
        "node": {
            "id": node.id,
            "label": node.label,
            "base_url": node.base_url,
            "enabled": node.enabled,
            "supports_codex": node.supports_codex,
            "supports_terminal": node.supports_terminal,
        },
        "health": health,
        "config": diagnostics,
        "setup": setup,
        "capabilities": capabilities,
        "runner_allowed_job_types": allowed_job_types,
        "interactive_supported": interactive_supported,
        "supported_actions": sorted(WEBAGENT_PLAYWRIGHT_ACTIONS),
        "supported_tools": sorted(TOOL_TO_ACTION.keys()),
    }


def webagent_overview(session: Session) -> dict[str, Any]:
    runs = list(session.exec(select(WebAgentRun).order_by(WebAgentRun.created_at.desc()).limit(200)).all())
    total = len(runs)
    status_counts: dict[str, int] = {}
    for row in runs:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    recent = [_row_payload(row) for row in runs[:8]]
    saved = sum(1 for r in runs if r.is_saved)
    useful = sum(1 for r in runs if r.is_useful)
    return {
        "summary": {
            "total_runs": total,
            "saved_reports": saved,
            "useful_runs": useful,
            "status_counts": status_counts,
        },
        "recent_runs": recent,
        "supported_run_types": sorted(WEBAGENT_PUBLIC_RUN_TYPES),
        "default_node_id": _default_node_id(),
    }
