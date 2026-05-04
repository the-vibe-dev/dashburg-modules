from __future__ import annotations

import json
import os
from typing import Any

from app.models.remoteops import RemoteOpsNode


SENSITIVE_TOKENS = ("token", "secret", "password", "api_key", "authorization", "bearer")
CONNECTION_OVERRIDE_KEYS = {
    "node_api_token",
    "webagent_node_api_token",
    "node_api_base",
    "webagent_node_api_base",
    "node_api_token_env",
    "node_artifacts_dir",
    "webagent_connection",
}


def _jloads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, row in value.items():
            key_str = str(key)
            lower = key_str.lower()
            if any(token in lower for token in SENSITIVE_TOKENS):
                out[key_str] = "***REDACTED***"
            else:
                out[key_str] = redact_sensitive(row)
        return out
    if isinstance(value, list):
        return [redact_sensitive(row) for row in value]
    return value


def drop_connection_overrides(payload: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(payload or {})
    out: dict[str, Any] = {}
    for key, value in src.items():
        if key in CONNECTION_OVERRIDE_KEYS:
            continue
        out[key] = value
    return out


def resolve_webagent_bridge_config(node: RemoteOpsNode) -> dict[str, Any]:
    notes = _jloads_dict(node.notes)
    webagent_notes = notes.get("webagent") if isinstance(notes.get("webagent"), dict) else {}
    webagent_notes = webagent_notes if isinstance(webagent_notes, dict) else {}

    base = _first_non_empty(
        webagent_notes.get("node_api_base"),
        webagent_notes.get("api_base"),
        os.getenv("WEBAGENT_NODE_API_BASE", ""),
        "http://127.0.0.1:9477",
    ).rstrip("/")
    token_env_name = _first_non_empty(
        webagent_notes.get("node_api_token_env"),
        os.getenv("WEBAGENT_NODE_API_TOKEN_ENV", ""),
        "WEBAGENT_NODE_API_TOKEN",
    )
    artifacts_dir = _first_non_empty(
        webagent_notes.get("node_artifacts_dir"),
        os.getenv("WEBAGENT_NODE_ARTIFACTS_DIR", ""),
        "/opt/dashburg/browser-qa-node/artifacts",
    )
    timeout_seconds = _int(
        webagent_notes.get("timeout_seconds") or os.getenv("WEBAGENT_TIMEOUT_SECONDS", ""),
        900,
        5,
        7200,
    )
    poll_interval_seconds = _float(
        webagent_notes.get("poll_interval_seconds") or os.getenv("WEBAGENT_POLL_INTERVAL_SECONDS", ""),
        2.0,
        0.2,
        30.0,
    )
    allow_runner_default_token = _bool(webagent_notes.get("allow_runner_default_token"), True)
    backend_token_present = bool(os.getenv(token_env_name, "").strip() or os.getenv("WEBAGENT_NODE_API_TOKEN", "").strip())

    issues: list[str] = []
    if not base:
        issues.append("missing_node_api_base")
    if not token_env_name and not allow_runner_default_token and not backend_token_present:
        issues.append("missing_node_api_token_source")

    configured = len(issues) == 0
    source = "node_notes" if webagent_notes else ("env" if os.getenv("WEBAGENT_NODE_API_BASE", "").strip() else "defaults")
    token_source = f"env:{token_env_name}" if backend_token_present else ("runner_default_or_env" if allow_runner_default_token else "missing")

    dispatch_params = {
        "node_api_base": base,
        "node_api_token_env": token_env_name,
        "node_artifacts_dir": artifacts_dir,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
    }
    diagnostics = {
        "configured": configured,
        "source": source,
        "node_api_base": base,
        "node_artifacts_dir": artifacts_dir,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "node_api_token_configured": bool(backend_token_present or allow_runner_default_token),
        "node_api_token_source": token_source,
        "issues": issues,
    }
    return {"dispatch_params": dispatch_params, "diagnostics": diagnostics}
