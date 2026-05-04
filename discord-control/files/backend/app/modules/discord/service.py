from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlmodel import Session, select

from app.core.paths import dashburg_data_dir
from app.models.discord import (
    DiscordApprovalRequest,
    DiscordAuditEvent,
    DiscordDispatchRequest,
    DiscordIntegrationSettings,
    DiscordPolicyDecision,
    DiscordRiskReview,
    DispatchExecutionResult,
    DispatchWorkerHeartbeat,
)
from app.modules.memory.service import build_memory_brief, search_memory, write_delta, write_session_index
from app.modules.orchestration.service import create_job as create_orchestration_job
from app.modules.remote_ops.service import get_nodes_health_status, list_nodes

try:
    import redis as redis_lib
except Exception:  # pragma: no cover
    redis_lib = None

_MANAGED_MEMORY_HEADER = "## Discord Learned Operational Notes"

_ALLOWED_ACTIONS = {
    "status.check",
    "logs.summary",
    "memory.search",
    "memory.append_candidate",
    "session.ask",
    "service.invoke_safe",
    "codex.launch_task",
    "agent.launch",
    "workflow.start",
    "dispatch.approve",
    "dispatch.reject",
}

_READ_ONLY_ACTIONS = {
    "status.check",
    "logs.summary",
    "memory.search",
    "session.ask",
    "service.invoke_safe",
}

_RISKY_ACTIONS = {
    "codex.launch_task",
    "agent.launch",
    "workflow.start",
}

_ACTION_CAPABILITIES = {
    "status.check": ["orchestration", "queue-worker"],
    "logs.summary": ["logs/status"],
    "memory.search": ["memory"],
    "memory.append_candidate": ["memory"],
    "session.ask": ["llm", "memory"],
    "service.invoke_safe": ["orchestration"],
    "codex.launch_task": ["codex", "orchestration"],
    "agent.launch": ["orchestration"],
    "workflow.start": ["orchestration", "queue-worker"],
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads_dict(raw: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
    except Exception:
        return fallback or {}
    return val if isinstance(val, dict) else (fallback or {})


def _json_loads_list(raw: str, fallback: list[str] | None = None) -> list[str]:
    try:
        val = json.loads(raw or "[]")
    except Exception:
        return fallback or []
    if not isinstance(val, list):
        return fallback or []
    return [str(v).strip() for v in val if str(v).strip()]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _mask_secret(secret: str) -> str:
    text = str(secret or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:3]}{'*' * (len(text) - 6)}{text[-3:]}"


def _normalize_id_list(value: Any) -> list[str]:
    candidates: list[str] = []
    if isinstance(value, list):
        candidates = [str(v).strip() for v in value]
    elif isinstance(value, str):
        candidates = re.split(r"[\s,]+", value.strip())

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        token = re.sub(r"[^0-9]", "", item)
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _to_iso(value: datetime | None) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def ensure_settings(session: Session) -> DiscordIntegrationSettings:
    row = session.get(DiscordIntegrationSettings, 1)
    if row:
        return row
    row = DiscordIntegrationSettings(id=1)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def settings_to_public(row: DiscordIntegrationSettings) -> dict[str, Any]:
    return {
        "enabled": row.enabled,
        "bridge_url": row.bridge_url,
        "bridge_auth_enabled": row.bridge_auth_enabled,
        "bridge_api_key_present": bool(row.bridge_api_key),
        "bridge_api_key_masked": _mask_secret(row.bridge_api_key),
        "bot_token_present": bool(row.bot_token),
        "bot_token_masked": _mask_secret(row.bot_token),
        "guild_sync_mode": row.guild_sync_mode,
        "heartbeat_poll_seconds": row.heartbeat_poll_seconds,
        "allowed_user_ids": _json_loads_list(row.allowed_user_ids_json),
        "allowed_guild_ids": _json_loads_list(row.allowed_guild_ids_json),
        "allowed_channel_ids": _json_loads_list(row.allowed_channel_ids_json),
        "allowed_role_ids": _json_loads_list(row.allowed_role_ids_json),
        "allowed_approver_ids": _json_loads_list(row.allowed_approver_ids_json),
        "dm_disabled": row.dm_disabled,
        "read_only_mode": row.read_only_mode,
        "dispatch_enabled": row.dispatch_enabled,
        "require_explicit_approval": row.require_explicit_approval,
        "direct_qwen_fallback_enabled": row.direct_qwen_fallback_enabled,
        "policy_deterministic_enabled": row.policy_deterministic_enabled,
        "llm_reviewer_enabled": row.llm_reviewer_enabled,
        "llm_reviewer_model": row.llm_reviewer_model,
        "isolated_execution_required_for_risky": row.isolated_execution_required_for_risky,
        "direct_execution_disabled": row.direct_execution_disabled,
        "raw_shell_disabled": row.raw_shell_disabled,
        "session_provider": row.session_provider,
        "default_model": row.default_model,
        "default_temperature": row.default_temperature,
        "max_context_budget": row.max_context_budget,
        "session_ttl_seconds": row.session_ttl_seconds,
        "future_tool_use_enabled": row.future_tool_use_enabled,
        "orchestration_first_routing": row.orchestration_first_routing,
        "memory_source_primary": row.memory_source_primary,
        "memory_source_fallback": row.memory_source_fallback,
        "memory_append_enabled": row.memory_append_enabled,
        "memory_append_mode": row.memory_append_mode,
        "memory_write_guardrails": row.memory_write_guardrails,
        "memory_relevance_threshold": row.memory_relevance_threshold,
        "last_indexed_at": _to_iso(row.last_indexed_at),
        "last_append_at": _to_iso(row.last_append_at),
        "last_heartbeat_at": _to_iso(row.last_heartbeat_at),
        "last_seen_at": _to_iso(row.last_seen_at),
        "last_error": row.last_error,
        "updated_at": _to_iso(row.updated_at),
    }


def update_settings(session: Session, payload: dict[str, Any]) -> DiscordIntegrationSettings:
    row = ensure_settings(session)

    if "enabled" in payload:
        row.enabled = bool(payload.get("enabled"))
    if payload.get("bridge_url") is not None:
        row.bridge_url = str(payload.get("bridge_url") or row.bridge_url).strip() or row.bridge_url
    if "bridge_auth_enabled" in payload:
        row.bridge_auth_enabled = bool(payload.get("bridge_auth_enabled"))
    if payload.get("bridge_api_key") is not None:
        key = str(payload.get("bridge_api_key") or "").strip()
        if key:
            row.bridge_api_key = key
    if payload.get("bot_token") is not None:
        token = str(payload.get("bot_token") or "").strip()
        if token:
            row.bot_token = token
    if payload.get("guild_sync_mode") is not None:
        row.guild_sync_mode = str(payload.get("guild_sync_mode") or row.guild_sync_mode).strip() or row.guild_sync_mode
    if payload.get("heartbeat_poll_seconds") is not None:
        row.heartbeat_poll_seconds = max(5, min(3600, int(payload.get("heartbeat_poll_seconds") or row.heartbeat_poll_seconds)))

    for key, attr in (
        ("allowed_user_ids", "allowed_user_ids_json"),
        ("allowed_guild_ids", "allowed_guild_ids_json"),
        ("allowed_channel_ids", "allowed_channel_ids_json"),
        ("allowed_role_ids", "allowed_role_ids_json"),
        ("allowed_approver_ids", "allowed_approver_ids_json"),
    ):
        if key in payload:
            setattr(row, attr, _json_dumps(_normalize_id_list(payload.get(key))))

    for key in (
        "dm_disabled",
        "read_only_mode",
        "dispatch_enabled",
        "require_explicit_approval",
        "direct_qwen_fallback_enabled",
        "policy_deterministic_enabled",
        "llm_reviewer_enabled",
        "isolated_execution_required_for_risky",
        "direct_execution_disabled",
        "raw_shell_disabled",
        "future_tool_use_enabled",
        "orchestration_first_routing",
        "memory_append_enabled",
        "memory_write_guardrails",
    ):
        if key in payload:
            setattr(row, key, bool(payload.get(key)))

    if payload.get("llm_reviewer_model") is not None:
        row.llm_reviewer_model = str(payload.get("llm_reviewer_model") or row.llm_reviewer_model).strip() or row.llm_reviewer_model
    if payload.get("session_provider") is not None:
        row.session_provider = str(payload.get("session_provider") or row.session_provider).strip() or row.session_provider
    if payload.get("default_model") is not None:
        row.default_model = str(payload.get("default_model") or row.default_model).strip() or row.default_model
    if payload.get("default_temperature") is not None:
        row.default_temperature = max(0.0, min(2.0, float(payload.get("default_temperature") or row.default_temperature)))
    if payload.get("max_context_budget") is not None:
        row.max_context_budget = max(256, min(128000, int(payload.get("max_context_budget") or row.max_context_budget)))
    if payload.get("session_ttl_seconds") is not None:
        row.session_ttl_seconds = max(300, min(604800, int(payload.get("session_ttl_seconds") or row.session_ttl_seconds)))
    if payload.get("memory_source_primary") is not None:
        row.memory_source_primary = str(payload.get("memory_source_primary") or row.memory_source_primary).strip() or row.memory_source_primary
    if payload.get("memory_source_fallback") is not None:
        row.memory_source_fallback = str(payload.get("memory_source_fallback") or row.memory_source_fallback).strip() or row.memory_source_fallback
    if payload.get("memory_append_mode") is not None:
        row.memory_append_mode = str(payload.get("memory_append_mode") or row.memory_append_mode).strip() or row.memory_append_mode
    if payload.get("memory_relevance_threshold") is not None:
        row.memory_relevance_threshold = max(0.0, min(1.0, float(payload.get("memory_relevance_threshold") or row.memory_relevance_threshold)))

    row.updated_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _redis_url() -> str:
    return str(os.getenv("DISCORD_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()


class DiscordSessionService:
    def redis_status(self) -> dict[str, Any]:
        if redis_lib is None:
            return {"ok": False, "reachable": False, "redis_url": _redis_url(), "error": "redis package not installed"}
        try:
            client = redis_lib.Redis.from_url(_redis_url(), decode_responses=True, socket_timeout=1.5)
            pong = client.ping()
            info = client.info("server")
            return {
                "ok": bool(pong),
                "reachable": bool(pong),
                "redis_url": _redis_url(),
                "version": str(info.get("redis_version") or ""),
                "error": "",
            }
        except Exception as exc:
            return {"ok": False, "reachable": False, "redis_url": _redis_url(), "error": str(exc)}

    def _session_key(self, user_id: str, guild_id: str, channel_id: str) -> str:
        gid = guild_id or "dm"
        cid = channel_id or "dm"
        return f"dashburg:discord:session:v1:{gid}:{cid}:{user_id}"

    def resolve_session(self, settings: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
        status = self.redis_status()
        user_id = str(payload.get("user_id") or "").strip()
        guild_id = str(payload.get("guild_id") or "").strip()
        channel_id = str(payload.get("channel_id") or "").strip()
        if not user_id:
            return {"ok": False, "error": "user_id is required", "redis": status}
        if not status.get("reachable"):
            return {"ok": False, "error": "redis unreachable", "redis": status}
        if redis_lib is None:
            return {"ok": False, "error": "redis package not installed", "redis": status}

        key = self._session_key(user_id, guild_id, channel_id)
        model = str(payload.get("model") or settings.default_model).strip() or settings.default_model
        temperature = float(payload.get("temperature") if payload.get("temperature") is not None else settings.default_temperature)
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

        client = redis_lib.Redis.from_url(_redis_url(), decode_responses=True, socket_timeout=2.0)
        now = _now_iso()
        existing = client.hgetall(key)
        created = not bool(existing)
        new_fields = {
            "user_id": user_id,
            "guild_id": guild_id or "dm",
            "channel_id": channel_id or "dm",
            "last_seen": now,
            "updated_at": now,
            "model": model,
            "last_used_model": model,
            "temperature": f"{temperature:.3f}",
            "metadata_json": _json_dumps(meta),
        }
        if created:
            new_fields["created_at"] = now
        client.hset(key, mapping=new_fields)
        client.expire(key, int(settings.session_ttl_seconds))

        # keep compact recent history list for low-token continuity
        history_key = f"{key}:recent"
        if payload.get("prompt_summary"):
            client.lpush(history_key, str(payload.get("prompt_summary"))[:512])
            client.ltrim(history_key, 0, 15)
            client.expire(history_key, int(settings.session_ttl_seconds))

        write_session_index(
            {
                "session_id": key,
                "source": "discord",
                "user_id": user_id,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "model": model,
                "ts": now,
            }
        )

        return {
            "ok": True,
            "session": {
                "session_key": key,
                "created": created,
                "model": model,
                "temperature": temperature,
                "ttl_seconds": settings.session_ttl_seconds,
                "last_seen": now,
                "state": {**existing, **new_fields},
            },
            "redis": status,
        }


@dataclass
class _MemorySource:
    path: Path
    exists: bool


class DiscordMemoryService:
    def __init__(self, settings: DiscordIntegrationSettings):
        self.settings = settings
        self._index_path = dashburg_data_dir() / "discord" / "discord_mem_index.json"

    def _resolve_sources(self) -> list[_MemorySource]:
        primary = Path(str(self.settings.memory_source_primary).strip()).expanduser()
        fallback = Path(str(self.settings.memory_source_fallback).strip()).expanduser()
        out: list[_MemorySource] = []
        for path in (primary, fallback):
            p = path.resolve() if path.exists() else path
            if any(row.path == p for row in out):
                continue
            out.append(_MemorySource(path=p, exists=p.exists()))
        return out

    def preferred_source(self) -> _MemorySource:
        rows = self._resolve_sources()
        for row in rows:
            if row.exists:
                return row
        return rows[0]

    def _parse_sections(self, text: str) -> list[dict[str, Any]]:
        lines = text.splitlines()
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for idx, line in enumerate(lines, start=1):
            m = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
            if m:
                if current is not None:
                    current["char_count"] = len("\n".join(current.pop("_lines", [])))
                    sections.append(current)
                current = {"heading": m.group(2).strip(), "level": len(m.group(1)), "line_start": idx, "_lines": []}
                continue
            if current is not None:
                current["_lines"].append(line)
        if current is not None:
            current["char_count"] = len("\n".join(current.pop("_lines", [])))
            sections.append(current)
        return sections

    def index_status(self) -> dict[str, Any]:
        src = self.preferred_source()
        index = {}
        if self._index_path.exists():
            try:
                index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception:
                index = {}
        sections = index.get("sections") if isinstance(index.get("sections"), list) else []
        return {
            "source_path": str(src.path),
            "source_exists": src.exists,
            "candidate_sources": [str(s.path) for s in self._resolve_sources()],
            "last_indexed_at": index.get("indexed_at") or _to_iso(self.settings.last_indexed_at),
            "last_append_at": _to_iso(self.settings.last_append_at),
            "indexed_section_count": len(sections),
            "summary": {
                "top_sections": [s.get("heading") for s in sections[:8] if isinstance(s, dict)],
                "managed_append_header": _MANAGED_MEMORY_HEADER,
                "append_mode": self.settings.memory_append_mode,
                "append_enabled": self.settings.memory_append_enabled,
                "note": "Discord uses indexed MEM context, not full MEM.md dumps.",
            },
            "healthy": bool(src.exists),
        }

    def reindex(self, session: Session, dry_run: bool = False) -> dict[str, Any]:
        src = self.preferred_source()
        if not src.exists:
            return {"ok": False, "error": "MEM.md source file not found", "source_path": str(src.path), "dry_run": dry_run}
        content = src.path.read_text(encoding="utf-8", errors="replace")
        sections = self._parse_sections(content)
        payload = {
            "indexed_at": _now_iso(),
            "source_path": str(src.path),
            "source_size_bytes": len(content.encode("utf-8", errors="ignore")),
            "source_mtime": src.path.stat().st_mtime,
            "sections": sections,
        }
        if not dry_run:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            self._index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.settings.last_indexed_at = _utcnow()
            self.settings.updated_at = _utcnow()
            session.add(self.settings)
            session.commit()
        return {
            "ok": True,
            "dry_run": dry_run,
            "source_path": str(src.path),
            "indexed_section_count": len(sections),
            "indexed_at": payload["indexed_at"],
        }

    def append_operational_note(self, session: Session, note: str, *, kind: str, relevance: float, dry_run: bool) -> dict[str, Any]:
        text = str(note or "").strip()
        if len(text) < 20:
            return {"ok": False, "accepted": False, "reason": "note too short", "dry_run": dry_run}
        if not self.settings.memory_append_enabled:
            return {"ok": False, "accepted": False, "reason": "memory append disabled", "dry_run": dry_run}
        if self.settings.memory_write_guardrails and relevance < self.settings.memory_relevance_threshold:
            return {"ok": False, "accepted": False, "reason": "below relevance threshold", "dry_run": dry_run}

        src = self.preferred_source()
        if not src.exists:
            return {"ok": False, "accepted": False, "reason": "MEM.md source missing", "dry_run": dry_run}

        body = src.path.read_text(encoding="utf-8", errors="replace")
        if text.lower() in body.lower():
            return {"ok": True, "accepted": False, "reason": "duplicate", "dry_run": dry_run}

        line = f"- [{_now_iso()}] ({kind}) {text}"
        if _MANAGED_MEMORY_HEADER in body:
            updated = body.replace(_MANAGED_MEMORY_HEADER, f"{_MANAGED_MEMORY_HEADER}\n{line}", 1)
        else:
            updated = f"{body.rstrip()}\n\n{_MANAGED_MEMORY_HEADER}\n{line}\n"

        if not dry_run:
            src.path.write_text(updated, encoding="utf-8")
            self.settings.last_append_at = _utcnow()
            self.settings.updated_at = _utcnow()
            session.add(self.settings)
            session.commit()
            write_delta({"kind": "discord_memory_append", "state": "captured", "summary": text[:240], "body": text, "source": "discord", "ts": _now_iso()})

        return {"ok": True, "accepted": True, "line_preview": line, "source_path": str(src.path), "dry_run": dry_run}


class DiscordBridgeService:
    async def check(self, settings: DiscordIntegrationSettings) -> dict[str, Any]:
        base = str(settings.bridge_url or "").strip().rstrip("/")
        if not base:
            return {"ok": False, "reachable": False, "online": False, "error": "bridge_url not configured", "status_code": None}
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.bridge_auth_enabled and settings.bridge_api_key:
            headers["X-Dashburg-Bridge-Key"] = settings.bridge_api_key

        for endpoint in ("/status", "/health"):
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{base}{endpoint}", headers=headers)
                payload = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                payload = payload if isinstance(payload, dict) else {}
                online = bool(payload.get("bot_online") or payload.get("online") or str(payload.get("status") or "").lower() in {"ok", "healthy", "online", "ready"})
                return {
                    "ok": resp.status_code < 400,
                    "reachable": True,
                    "online": online,
                    "status_code": resp.status_code,
                    "endpoint": endpoint,
                    "last_heartbeat": payload.get("last_heartbeat") or payload.get("heartbeat_at"),
                    "last_seen": payload.get("last_seen") or payload.get("last_seen_at"),
                    "last_error": payload.get("last_error") or "",
                    "payload": payload,
                    "error": "" if resp.status_code < 400 else f"status {resp.status_code}",
                }
            except Exception as exc:
                last_error = str(exc)
        return {"ok": False, "reachable": False, "online": False, "status_code": None, "endpoint": "", "last_heartbeat": None, "last_seen": None, "last_error": last_error, "payload": {}, "error": last_error}


class DiscordDispatchRegistry:
    def list_targets(self, session: Session, settings: DiscordIntegrationSettings) -> dict[str, Any]:
        nodes = list_nodes(session)
        health = {str(r.get("node_id")): r for r in get_nodes_health_status(session).get("nodes", [])}

        targets: list[dict[str, Any]] = []
        for node in nodes:
            node_id = str(node.get("id") or "")
            h = health.get(node_id, {})
            caps: set[str] = set()
            if bool(node.get("supports_codex")):
                caps.add("codex")
            if bool(node.get("supports_terminal")):
                caps.add("shell")
            for raw in (node.get("allowed_services") or []):
                low = str(raw).lower()
                if "ollama" in low:
                    caps.add("llm")
                if "webagent" in low:
                    caps.add("web-agent")
                if "topic" in low:
                    caps.add("topic-research")
                if "orchestr" in low:
                    caps.add("orchestration")
            caps_obj = node.get("capabilities") if isinstance(node.get("capabilities"), dict) else {}
            for key, val in caps_obj.items():
                if bool(val):
                    caps.add(str(key).replace("_", "-"))

            requires_isolated = bool("codex" in caps or "shell" in caps)
            targets.append(
                {
                    "service_id": node_id,
                    "id": node_id,
                    "display_name": node.get("label") or node_id,
                    "label": node.get("label") or node_id,
                    "host": str(node.get("base_url") or ""),
                    "kind": "remote_node",
                    "capabilities": sorted(caps),
                    "health": h.get("status") or "unknown",
                    "health_status": h.get("status") or "unknown",
                    "online": bool(h.get("ok")),
                    "configured": bool(node.get("enabled")),
                    "dispatch_enabled": bool(settings.dispatch_enabled),
                    "dispatchable": False,
                    "discord_safe": bool(settings.read_only_mode or settings.require_explicit_approval),
                    "safe_for_discord": bool(settings.read_only_mode or settings.require_explicit_approval),
                    "requires_isolated_execution": requires_isolated,
                    "supported_action_types": [k for k in _ALLOWED_ACTIONS if not (k in _RISKY_ACTIONS and requires_isolated and settings.read_only_mode)],
                    "write_capable": bool("codex" in caps or "shell" in caps),
                    "approval_required_by_default": requires_isolated,
                    "phase1_blocked": False,
                    "last_seen_at": node.get("last_seen_at"),
                }
            )

        targets.extend(
            [
                {
                    "service_id": "dashburg-orchestration",
                    "id": "dashburg-orchestration",
                    "display_name": "Dashburg Orchestration",
                    "label": "Dashburg Orchestration",
                    "host": "local",
                    "kind": "service",
                    "capabilities": ["orchestration", "queue-worker"],
                    "health": "ready",
                    "health_status": "ready",
                    "online": True,
                    "configured": True,
                    "dispatch_enabled": True,
                    "dispatchable": True,
                    "discord_safe": True,
                    "safe_for_discord": True,
                    "requires_isolated_execution": False,
                    "supported_action_types": ["status.check", "workflow.start", "service.invoke_safe"],
                    "write_capable": False,
                    "approval_required_by_default": False,
                    "phase1_blocked": False,
                    "last_seen_at": _now_iso(),
                },
                {
                    "service_id": "dashburg-memory",
                    "id": "dashburg-memory",
                    "display_name": "Dashburg Memory",
                    "label": "Dashburg Memory",
                    "host": "local",
                    "kind": "service",
                    "capabilities": ["memory"],
                    "health": "ready",
                    "health_status": "ready",
                    "online": True,
                    "configured": True,
                    "dispatch_enabled": True,
                    "dispatchable": True,
                    "discord_safe": True,
                    "safe_for_discord": True,
                    "requires_isolated_execution": False,
                    "supported_action_types": ["memory.search", "memory.append_candidate", "session.ask"],
                    "write_capable": False,
                    "approval_required_by_default": False,
                    "phase1_blocked": False,
                    "last_seen_at": _now_iso(),
                },
            ]
        )

        return {
            "targets": targets,
            "summary": {
                "total": len(targets),
                "online": sum(1 for t in targets if t.get("online")),
                "dispatch_ready": sum(1 for t in targets if t.get("dispatchable")),
                "isolated_only": sum(1 for t in targets if t.get("requires_isolated_execution")),
                "phase": "phase2",
            },
        }


class DispatchAdapter(Protocol):
    action_types: set[str]

    def execute(self, session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
        ...


class StatusAdapter:
    action_types = {"status.check", "service.invoke_safe"}

    def execute(self, session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
        targets = DiscordDispatchRegistry().list_targets(session, settings)
        target_id = str(normalized.get("target") or "").strip()
        rows = targets.get("targets", [])
        if target_id:
            rows = [r for r in rows if str(r.get("id")) == target_id or str(r.get("service_id")) == target_id]
        return {"ok": True, "kind": "status", "target": target_id or "all", "items": rows[:20], "summary": targets.get("summary", {})}


class LogsAdapter:
    action_types = {"logs.summary"}

    def execute(self, session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
        args = normalized.get("args") if isinstance(normalized.get("args"), dict) else {}
        path = str(args.get("path") or dashburg_data_dir() / "backend-8321.log")
        try:
            p = Path(path).expanduser()
            text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
            lines = text.splitlines()[-80:]
            return {"ok": True, "path": str(p), "line_count": len(lines), "tail": lines[-20:], "summary": ("\n".join(lines[-10:]))[:1200]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class MemoryAdapter:
    action_types = {"memory.search", "memory.append_candidate", "session.ask"}

    def execute(self, session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
        action_type = str(normalized.get("action_type") or "")
        args = normalized.get("args") if isinstance(normalized.get("args"), dict) else {}
        if action_type == "memory.search":
            query = str(args.get("query") or normalized.get("prompt") or "").strip()
            payload = {"query": query, "limit": int(args.get("limit") or 12), "include_docs": bool(args.get("include_docs", False)), "include_knowledge": True}
            return {"ok": True, "query": query, "results": search_memory(payload)}
        if action_type == "memory.append_candidate":
            note = str(args.get("note") or normalized.get("prompt") or "").strip()
            rel = float(args.get("relevance") or 0.9)
            out = DiscordMemoryService(settings).append_operational_note(session, note=note, kind="discord_candidate", relevance=rel, dry_run=True)
            return {"ok": True, "candidate": out, "auto_write": False}
        # session.ask
        question = str(args.get("query") or normalized.get("prompt") or "").strip()
        brief = build_memory_brief({"query": question, "max_chars": min(settings.max_context_budget, 1800)})
        answer = (
            "Session context assembled from indexed memory. "
            "Use this brief to answer safely and route execution requests through policy+approval workflow."
        )
        return {"ok": True, "question": question, "context_brief": brief.get("brief", ""), "answer": answer, "references": brief.get("references", [])}


class OrchestrationLaunchAdapter:
    action_types = {"codex.launch_task", "agent.launch", "workflow.start"}

    def execute(self, session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
        args = normalized.get("args") if isinstance(normalized.get("args"), dict) else {}
        target_node = str(args.get("target_node") or "").strip()
        repo_path = str(args.get("repo_path") or "").strip()
        prompt = str(args.get("prompt") or normalized.get("prompt") or "").strip()
        if not target_node or not repo_path:
            return {"ok": False, "error": "target_node and repo_path are required"}

        job = create_orchestration_job(
            session,
            {
                "title": str(args.get("title") or f"discord:{normalized.get('action_type')}")[:180],
                "task_type": "codex_task" if normalized.get("action_type") == "codex.launch_task" else "agent_task",
                "target_node": target_node,
                "repo_path": repo_path,
                "workspace_path": str(args.get("workspace_path") or repo_path),
                "prompt": prompt,
                "instructions": str(args.get("instructions") or "Dispatched from Discord via Dashburg policy-controlled route."),
                "metadata": {
                    "source": "discord",
                    "audit_id": req.audit_id,
                    "request_id": req.id,
                    "action_type": normalized.get("action_type"),
                },
                "priority": int(args.get("priority") or 120),
                "timeout_seconds": int(args.get("timeout_seconds") or 3600),
            },
        )
        return {
            "ok": True,
            "queued": True,
            "orchestration_job_id": job.id,
            "status": job.status,
            "target_node": job.target_node,
            "repo_path": job.repo_path,
        }


_ADAPTERS: list[DispatchAdapter] = [StatusAdapter(), LogsAdapter(), MemoryAdapter(), OrchestrationLaunchAdapter()]


def _adapter_for(action_type: str) -> DispatchAdapter | None:
    for adapter in _ADAPTERS:
        if action_type in adapter.action_types:
            return adapter
    return None


@dataclass
class NormalizedAction:
    action_type: str
    target: str
    args: dict[str, Any]
    prompt: str
    capability_requirements: list[str]
    source_command: str


@dataclass
class PolicyOutcome:
    decision: str  # allow | deny | require_approval | downgrade
    risk_level: str
    reasons: list[str]
    approval_required: bool
    isolated_required: bool
    downgraded_action_type: str


def _normalize_action(payload: dict[str, Any]) -> NormalizedAction:
    action_type = str(payload.get("action_type") or "").strip().lower()
    command = str(payload.get("command") or "").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    prompt = str(payload.get("prompt") or args.get("prompt") or "").strip()
    target = str(payload.get("target") or args.get("target") or "").strip()

    # Slash-like command fallback parser
    if not action_type and command:
        cmd = command.lower().strip()
        if cmd.startswith("/dash status"):
            action_type = "status.check"
        elif cmd.startswith("/dash memory"):
            action_type = "memory.search"
        elif cmd.startswith("/dash ask"):
            action_type = "session.ask"
        elif cmd.startswith("/dash services"):
            action_type = "status.check"
        elif cmd.startswith("/dash codex"):
            action_type = "codex.launch_task"
        elif cmd.startswith("/dash agent"):
            action_type = "agent.launch"
        elif cmd.startswith("/dash approve"):
            action_type = "dispatch.approve"
        elif cmd.startswith("/dash reject"):
            action_type = "dispatch.reject"

    if action_type not in _ALLOWED_ACTIONS:
        action_type = "status.check"

    return NormalizedAction(
        action_type=action_type,
        target=target,
        args=args,
        prompt=prompt,
        capability_requirements=_ACTION_CAPABILITIES.get(action_type, []),
        source_command=command,
    )


def _role_intersects(allowed: list[str], have: list[str]) -> bool:
    if not allowed:
        return True
    if not have:
        return False
    return bool(set(allowed).intersection(set(have)))


def _is_allowed_identity(settings: DiscordIntegrationSettings, requester: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    uid = str(requester.get("user_id") or "").strip()
    gid = str(requester.get("guild_id") or "").strip()
    cid = str(requester.get("channel_id") or "").strip()
    is_dm = bool(requester.get("is_dm")) or not gid
    role_ids = [str(v).strip() for v in (requester.get("role_ids") if isinstance(requester.get("role_ids"), list) else []) if str(v).strip()]

    if settings.dm_disabled and is_dm:
        reasons.append("dm disabled")

    allowed_users = _json_loads_list(settings.allowed_user_ids_json)
    allowed_guilds = _json_loads_list(settings.allowed_guild_ids_json)
    allowed_channels = _json_loads_list(settings.allowed_channel_ids_json)
    allowed_roles = _json_loads_list(settings.allowed_role_ids_json)

    if allowed_users and uid not in allowed_users:
        reasons.append("user not allowlisted")
    if allowed_guilds and gid and gid not in allowed_guilds:
        reasons.append("guild not allowlisted")
    if allowed_channels and cid and cid not in allowed_channels:
        reasons.append("channel not allowlisted")
    if allowed_roles and not _role_intersects(allowed_roles, role_ids):
        reasons.append("role not allowlisted")

    return (len(reasons) == 0), reasons


def evaluate_policy(
    settings: DiscordIntegrationSettings,
    normalized: NormalizedAction,
    requester: dict[str, Any],
    dispatch_target: dict[str, Any] | None,
) -> PolicyOutcome:
    reasons: list[str] = []
    decision = "allow"
    risk = "low"
    approval_required = False
    isolated_required = False
    downgraded_action_type = ""

    identity_ok, identity_reasons = _is_allowed_identity(settings, requester)
    if not identity_ok:
        return PolicyOutcome("deny", "high", identity_reasons, True, False, "")

    if not settings.enabled:
        return PolicyOutcome("deny", "high", ["discord integration disabled"], True, False, "")
    if not settings.dispatch_enabled and normalized.action_type in _RISKY_ACTIONS:
        return PolicyOutcome("deny", "high", ["dispatch disabled"], True, False, "")

    if normalized.action_type not in _ALLOWED_ACTIONS:
        return PolicyOutcome("deny", "high", ["action type not allowed"], True, False, "")

    if settings.read_only_mode and normalized.action_type not in _READ_ONLY_ACTIONS:
        decision = "downgrade"
        downgraded_action_type = "status.check"
        reasons.append("read-only mode downgraded action")
        risk = "medium"

    if normalized.action_type in _RISKY_ACTIONS:
        risk = "high"
        if settings.require_explicit_approval:
            decision = "require_approval"
            approval_required = True
            reasons.append("explicit approval required")

    if normalized.action_type in {"codex.launch_task", "agent.launch", "workflow.start"}:
        isolated_required = bool(settings.isolated_execution_required_for_risky)
        if settings.direct_execution_disabled:
            reasons.append("direct execution disabled; queue/worker or orchestrator only")

    if normalized.action_type == "service.invoke_safe" and settings.raw_shell_disabled:
        reasons.append("raw shell disabled")

    if dispatch_target is not None:
        if not dispatch_target.get("configured"):
            return PolicyOutcome("deny", "high", reasons + ["target not configured"], True, isolated_required, downgraded_action_type)
        if not dispatch_target.get("online"):
            reasons.append("target currently offline")
        if normalized.capability_requirements:
            target_caps = set(str(c) for c in (dispatch_target.get("capabilities") or []))
            if not any(cap in target_caps for cap in normalized.capability_requirements):
                return PolicyOutcome("deny", "high", reasons + ["target lacks required capabilities"], True, isolated_required, downgraded_action_type)

    if decision == "allow" and settings.policy_deterministic_enabled:
        approval_required = approval_required or False

    return PolicyOutcome(decision, risk, reasons, approval_required, isolated_required, downgraded_action_type)


async def run_risk_review(settings: DiscordIntegrationSettings, normalized: NormalizedAction, policy: PolicyOutcome) -> dict[str, Any]:
    prompt = normalized.prompt.lower()
    indicators: list[str] = []
    if any(tok in prompt for tok in ["ignore previous", "bypass", "disable safety", "rm -rf", "drop table", "exfiltrate", "secret", "token"]):
        indicators.append("suspicious_prompt_pattern")
    if normalized.action_type in _RISKY_ACTIONS:
        indicators.append("high_impact_action")

    base = {
        "available": True,
        "reviewer": "heuristic",
        "model": settings.llm_reviewer_model,
        "intent_summary": f"{normalized.action_type} on {normalized.target or 'default target'}",
        "risk_level": "high" if indicators else policy.risk_level,
        "recommendation": "require_approval" if indicators else policy.decision,
        "confidence": 0.55 if indicators else 0.72,
        "suspicious_indicators": indicators,
        "explanation": "Heuristic reviewer output; deterministic policy remains source of truth.",
        "raw": {},
    }

    if not settings.llm_reviewer_enabled:
        base["available"] = False
        return base

    reviewer_url = str(os.getenv("DISCORD_POLICY_REVIEW_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    try:
        messages = [
            {"role": "system", "content": "Classify risk for a Discord-dispatched infra action. Return compact JSON with risk_level,recommendation,summary,indicators,confidence,explanation."},
            {"role": "user", "content": _json_dumps({"action_type": normalized.action_type, "target": normalized.target, "args": normalized.args, "prompt": normalized.prompt[:500], "policy": policy.__dict__})},
        ]
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{reviewer_url}/api/chat",
                json={"model": settings.llm_reviewer_model, "stream": False, "messages": messages},
            )
        resp.raise_for_status()
        payload = resp.json() if isinstance(resp.json(), dict) else {}
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        text = str(message.get("content") or "").strip()
        parsed = _json_loads_dict(text, {})
        if parsed:
            base.update(
                {
                    "reviewer": "llm",
                    "risk_level": str(parsed.get("risk_level") or base["risk_level"]),
                    "recommendation": str(parsed.get("recommendation") or base["recommendation"]),
                    "intent_summary": str(parsed.get("summary") or base["intent_summary"]),
                    "suspicious_indicators": [str(v) for v in (parsed.get("indicators") or base["suspicious_indicators"]) if str(v)],
                    "confidence": float(parsed.get("confidence") or base["confidence"]),
                    "explanation": str(parsed.get("explanation") or base["explanation"]),
                    "raw": payload,
                }
            )
    except Exception as exc:
        base["available"] = False
        base["explanation"] = f"LLM reviewer unavailable: {exc}. Deterministic policy applied."
    return base


def _build_target_lookup(session: Session, settings: DiscordIntegrationSettings) -> dict[str, dict[str, Any]]:
    rows = DiscordDispatchRegistry().list_targets(session, settings).get("targets", [])
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in (str(row.get("id") or ""), str(row.get("service_id") or "")):
            if key:
                out[key] = row
    return out


def _new_id() -> str:
    return uuid.uuid4().hex


def _create_audit_event(
    session: Session,
    *,
    audit_id: str,
    dispatch_request_id: str,
    event_type: str,
    actor: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> DiscordAuditEvent:
    row = DiscordAuditEvent(
        id=_new_id(),
        audit_id=audit_id,
        dispatch_request_id=dispatch_request_id,
        event_type=event_type,
        actor=actor,
        message=message,
        payload_json=_json_dumps(payload or {}),
        created_at=_utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _approval_ttl_seconds() -> int:
    return max(60, int(os.getenv("DISCORD_APPROVAL_TTL_SECONDS", "900")))


def _worker_token_hash(token: str) -> str:
    return _sha256(token)


def _create_approval(session: Session, req: DiscordDispatchRequest) -> tuple[DiscordApprovalRequest, str]:
    replay_token = secrets.token_urlsafe(24)
    row = DiscordApprovalRequest(
        id=_new_id(),
        audit_id=req.audit_id,
        dispatch_request_id=req.id,
        status="pending",
        expires_at=_utcnow() + timedelta(seconds=_approval_ttl_seconds()),
        replay_token_hash=_worker_token_hash(replay_token),
        created_at=_utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, replay_token


def _request_payload(row: DiscordDispatchRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "audit_id": row.audit_id,
        "status": row.status,
        "action_type": row.action_type,
        "target": row.target,
        "arguments": _json_loads_dict(row.arguments_json),
        "normalized": _json_loads_dict(row.normalized_json),
        "requester": {
            "user_id": row.requester_user_id,
            "guild_id": row.requester_guild_id,
            "channel_id": row.requester_channel_id,
            "role_ids": _json_loads_list(row.requester_role_ids_json),
            "name": row.requester_name,
        },
        "source": row.source,
        "source_command": row.source_command,
        "prompt_summary": row.prompt_summary,
        "session_key": row.session_key,
        "policy_decision": row.policy_decision,
        "policy_reason": row.policy_reason,
        "risk_level": row.risk_level,
        "approval_required": row.approval_required,
        "isolated_required": row.isolated_required,
        "dispatch_target_id": row.dispatch_target_id,
        "dispatch_worker_id": row.dispatch_worker_id,
        "dispatch_job_ref": row.dispatch_job_ref,
        "result": _json_loads_dict(row.result_json),
        "error": row.error,
        "created_at": _to_iso(row.created_at),
        "updated_at": _to_iso(row.updated_at),
        "started_at": _to_iso(row.started_at),
        "finished_at": _to_iso(row.finished_at),
    }


def _approval_payload(row: DiscordApprovalRequest, dispatch_row: DiscordDispatchRequest | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "audit_id": row.audit_id,
        "dispatch_request_id": row.dispatch_request_id,
        "status": row.status,
        "approver_user_id": row.approver_user_id,
        "decision_reason": row.decision_reason,
        "expires_at": _to_iso(row.expires_at),
        "created_at": _to_iso(row.created_at),
        "decided_at": _to_iso(row.decided_at),
        "request": _request_payload(dispatch_row) if dispatch_row else None,
    }


def _save_policy_row(session: Session, req: DiscordDispatchRequest, outcome: PolicyOutcome, normalized: NormalizedAction, requester: dict[str, Any]) -> DiscordPolicyDecision:
    row = DiscordPolicyDecision(
        id=_new_id(),
        audit_id=req.audit_id,
        dispatch_request_id=req.id,
        decision=outcome.decision,
        risk_level=outcome.risk_level,
        requires_approval=outcome.approval_required,
        downgraded_action_type=outcome.downgraded_action_type,
        isolated_required=outcome.isolated_required,
        reasons_json=_json_dumps(outcome.reasons),
        input_snapshot_json=_json_dumps(
            {
                "action": normalized.__dict__,
                "requester": requester,
            }
        ),
        created_at=_utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _save_review_row(session: Session, req: DiscordDispatchRequest, review: dict[str, Any]) -> DiscordRiskReview:
    row = DiscordRiskReview(
        id=_new_id(),
        audit_id=req.audit_id,
        dispatch_request_id=req.id,
        reviewer=str(review.get("reviewer") or "heuristic"),
        model=str(review.get("model") or ""),
        available=bool(review.get("available")),
        risk_level=str(review.get("risk_level") or "unknown"),
        recommendation=str(review.get("recommendation") or "none"),
        confidence=float(review.get("confidence") or 0.0),
        intent_summary=str(review.get("intent_summary") or ""),
        suspicious_indicators_json=_json_dumps(review.get("suspicious_indicators") or []),
        explanation=str(review.get("explanation") or ""),
        raw_json=_json_dumps(review.get("raw") or {}),
        created_at=_utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _set_request_status(session: Session, req: DiscordDispatchRequest, status: str, *, error: str = "", result: dict[str, Any] | None = None) -> None:
    req.status = status
    req.error = error[:5000]
    if result is not None:
        req.result_json = _json_dumps(result)
    req.updated_at = _utcnow()
    if status in {"running", "dispatched"} and req.started_at is None:
        req.started_at = _utcnow()
    if status in {"succeeded", "failed", "denied", "rejected", "expired"}:
        req.finished_at = _utcnow()
    session.add(req)
    session.commit()


def _dispatch_execute_local(session: Session, req: DiscordDispatchRequest, normalized: dict[str, Any], settings: DiscordIntegrationSettings) -> dict[str, Any]:
    action_type = str(normalized.get("action_type") or "")
    adapter = _adapter_for(action_type)
    if adapter is None:
        return {"ok": False, "error": f"no adapter for action {action_type}"}
    return adapter.execute(session, req, normalized, settings)


def _find_request(session: Session, request_id: str) -> DiscordDispatchRequest | None:
    return session.get(DiscordDispatchRequest, request_id)


def _find_pending_approval(session: Session, request_id: str) -> DiscordApprovalRequest | None:
    stmt = (
        select(DiscordApprovalRequest)
        .where(DiscordApprovalRequest.dispatch_request_id == request_id)
        .where(DiscordApprovalRequest.status == "pending")
        .order_by(DiscordApprovalRequest.created_at.desc())
    )
    return session.exec(stmt).first()


def _get_latest_policy_row(session: Session, request_id: str) -> DiscordPolicyDecision | None:
    stmt = (
        select(DiscordPolicyDecision)
        .where(DiscordPolicyDecision.dispatch_request_id == request_id)
        .order_by(DiscordPolicyDecision.created_at.desc())
    )
    return session.exec(stmt).first()


def _get_latest_review_row(session: Session, request_id: str) -> DiscordRiskReview | None:
    stmt = select(DiscordRiskReview).where(DiscordRiskReview.dispatch_request_id == request_id).order_by(DiscordRiskReview.created_at.desc())
    return session.exec(stmt).first()


async def ingest_dispatch_request(session: Session, settings: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    requester = payload.get("requester") if isinstance(payload.get("requester"), dict) else {}
    normalized = _normalize_action(payload)

    session_info = DiscordSessionService().resolve_session(
        settings,
        {
            "user_id": requester.get("user_id") or payload.get("session", {}).get("user_id"),
            "guild_id": requester.get("guild_id") or payload.get("session", {}).get("guild_id"),
            "channel_id": requester.get("channel_id") or payload.get("session", {}).get("channel_id"),
            "model": payload.get("session", {}).get("model") if isinstance(payload.get("session"), dict) else None,
            "temperature": payload.get("session", {}).get("temperature") if isinstance(payload.get("session"), dict) else None,
            "metadata": payload.get("session") if isinstance(payload.get("session"), dict) else {},
            "prompt_summary": normalized.prompt[:400],
        },
    )

    target_lookup = _build_target_lookup(session, settings)
    dispatch_target = target_lookup.get(normalized.target) if normalized.target else None

    policy = evaluate_policy(settings, normalized, requester, dispatch_target)
    review = await run_risk_review(settings, normalized, policy)

    if str(review.get("recommendation")) == "deny" and policy.decision != "deny":
        # advisory tighten: if reviewer flags explicit deny indicators, convert allow->require_approval
        policy = PolicyOutcome("require_approval", "high", policy.reasons + ["reviewer requested approval"], True, policy.isolated_required, policy.downgraded_action_type)

    audit_id = _new_id()
    request_id = _new_id()

    final_action_type = policy.downgraded_action_type or normalized.action_type
    req = DiscordDispatchRequest(
        id=request_id,
        audit_id=audit_id,
        status="received",
        action_type=final_action_type,
        target=normalized.target,
        arguments_json=_json_dumps(normalized.args),
        normalized_json=_json_dumps({**normalized.__dict__, "action_type": final_action_type}),
        requester_user_id=str(requester.get("user_id") or ""),
        requester_guild_id=str(requester.get("guild_id") or ""),
        requester_channel_id=str(requester.get("channel_id") or ""),
        requester_role_ids_json=_json_dumps(requester.get("role_ids") if isinstance(requester.get("role_ids"), list) else []),
        requester_name=str(requester.get("name") or ""),
        source="discord",
        source_command=normalized.source_command,
        prompt_summary=normalized.prompt[:1000],
        session_key=(session_info.get("session") or {}).get("session_key", "") if isinstance(session_info, dict) else "",
        policy_decision=policy.decision,
        policy_reason="; ".join(policy.reasons)[:2000],
        risk_level=policy.risk_level,
        approval_required=policy.approval_required,
        isolated_required=policy.isolated_required,
        dispatch_target_id=normalized.target,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(req)
    session.commit()
    session.refresh(req)

    _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="request.received", actor="discord", message="Discord request ingested", payload={"action_type": final_action_type, "target": normalized.target})
    _save_policy_row(session, req, policy, normalized, requester)
    _save_review_row(session, req, review)

    if policy.decision == "deny":
        _set_request_status(session, req, "denied", error="policy denied request")
        _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="policy.denied", actor="policy", message="Deterministic policy denied request", payload={"reasons": policy.reasons})
        return {
            "ok": False,
            "status": "denied",
            "audit_id": audit_id,
            "request": _request_payload(req),
            "policy": policy.__dict__,
            "review": review,
            "session": session_info,
        }

    if policy.decision == "require_approval":
        approval, replay_token = _create_approval(session, req)
        _set_request_status(session, req, "pending_approval")
        _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="approval.pending", actor="policy", message="Approval required before dispatch", payload={"approval_id": approval.id, "expires_at": _to_iso(approval.expires_at)})
        return {
            "ok": True,
            "status": "pending_approval",
            "audit_id": audit_id,
            "request": _request_payload(req),
            "approval": {**_approval_payload(approval, req), "replay_token": replay_token},
            "policy": policy.__dict__,
            "review": review,
            "session": session_info,
        }

    # allowed path
    if settings.direct_execution_disabled or policy.isolated_required:
        _set_request_status(session, req, "queued")
        _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="dispatch.queued", actor="policy", message="Request queued for worker", payload={"isolated_required": policy.isolated_required})
        return {"ok": True, "status": "queued", "audit_id": audit_id, "request": _request_payload(req), "policy": policy.__dict__, "review": review, "session": session_info}

    _set_request_status(session, req, "running")
    result = _dispatch_execute_local(session, req, _json_loads_dict(req.normalized_json), settings)
    if result.get("ok"):
        _set_request_status(session, req, "succeeded", result=result)
        _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="dispatch.succeeded", actor="adapter", message="Request executed by local adapter", payload={"result_summary": str(result)[:1000]})
    else:
        _set_request_status(session, req, "failed", error=str(result.get("error") or "adapter failed"), result=result)
        _create_audit_event(session, audit_id=audit_id, dispatch_request_id=req.id, event_type="dispatch.failed", actor="adapter", message="Local adapter failed", payload={"error": result.get("error")})

    return {"ok": bool(result.get("ok")), "status": req.status, "audit_id": audit_id, "request": _request_payload(req), "result": result, "policy": policy.__dict__, "review": review, "session": session_info}


def list_requests(session: Session, *, limit: int = 100, status: str = "") -> dict[str, Any]:
    stmt = select(DiscordDispatchRequest).order_by(DiscordDispatchRequest.created_at.desc())
    if status:
        stmt = stmt.where(DiscordDispatchRequest.status == status)
    rows = list(session.exec(stmt).all())[: max(1, min(limit, 500))]
    return {"items": [_request_payload(row) for row in rows]}


def get_request_detail(session: Session, request_id: str) -> dict[str, Any]:
    row = _find_request(session, request_id)
    if row is None:
        return {"ok": False, "error": "request not found"}
    policy = _get_latest_policy_row(session, row.id)
    review = _get_latest_review_row(session, row.id)
    approval = _find_pending_approval(session, row.id)
    events = list(
        session.exec(
            select(DiscordAuditEvent).where(DiscordAuditEvent.audit_id == row.audit_id).order_by(DiscordAuditEvent.created_at.asc())
        ).all()
    )
    return {
        "ok": True,
        "request": _request_payload(row),
        "policy": {
            "decision": policy.decision,
            "risk_level": policy.risk_level,
            "requires_approval": policy.requires_approval,
            "reasons": _json_loads_list(policy.reasons_json),
            "isolated_required": policy.isolated_required,
            "created_at": _to_iso(policy.created_at),
        }
        if policy
        else None,
        "review": {
            "reviewer": review.reviewer,
            "available": review.available,
            "risk_level": review.risk_level,
            "recommendation": review.recommendation,
            "confidence": review.confidence,
            "intent_summary": review.intent_summary,
            "suspicious_indicators": _json_loads_list(review.suspicious_indicators_json),
            "explanation": review.explanation,
            "created_at": _to_iso(review.created_at),
        }
        if review
        else None,
        "pending_approval": _approval_payload(approval, row) if approval else None,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "actor": e.actor,
                "message": e.message,
                "payload": _json_loads_dict(e.payload_json),
                "created_at": _to_iso(e.created_at),
            }
            for e in events
        ],
    }


def list_approvals(session: Session, *, status: str = "pending", limit: int = 100) -> dict[str, Any]:
    stmt = select(DiscordApprovalRequest).order_by(DiscordApprovalRequest.created_at.desc())
    if status:
        stmt = stmt.where(DiscordApprovalRequest.status == status)
    rows = list(session.exec(stmt).all())[: max(1, min(limit, 200))]
    out: list[dict[str, Any]] = []
    now = _utcnow()
    for row in rows:
        req = _find_request(session, row.dispatch_request_id)
        if row.status == "pending" and row.expires_at and row.expires_at < now:
            row.status = "expired"
            row.decided_at = now
            session.add(row)
            session.commit()
            if req is not None and req.status == "pending_approval":
                _set_request_status(session, req, "expired", error="approval expired")
        out.append(_approval_payload(row, req))
    return {"items": out}


def approve_request(session: Session, settings: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("dispatch_request_id") or "").strip()
    approver_user_id = str(payload.get("approver_user_id") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    replay_token = str(payload.get("replay_token") or "").strip()

    req = _find_request(session, request_id)
    if req is None:
        return {"ok": False, "error": "request not found"}

    approval = _find_pending_approval(session, request_id)
    if approval is None:
        return {"ok": False, "error": "pending approval not found"}

    allowed = _json_loads_list(settings.allowed_approver_ids_json)
    if allowed and approver_user_id not in allowed:
        return {"ok": False, "error": "approver user not allowlisted"}

    if approval.expires_at and approval.expires_at < _utcnow():
        approval.status = "expired"
        approval.decided_at = _utcnow()
        session.add(approval)
        session.commit()
        _set_request_status(session, req, "expired", error="approval expired")
        return {"ok": False, "error": "approval expired"}

    if _worker_token_hash(replay_token) != approval.replay_token_hash:
        return {"ok": False, "error": "invalid replay token"}

    approval.status = "approved"
    approval.approver_user_id = approver_user_id
    approval.decision_reason = reason
    approval.decided_at = _utcnow()
    session.add(approval)
    session.commit()

    _set_request_status(session, req, "queued")
    _create_audit_event(session, audit_id=req.audit_id, dispatch_request_id=req.id, event_type="approval.approved", actor=approver_user_id or "approver", message="Approval granted", payload={"reason": reason})
    return {"ok": True, "status": "queued", "request": _request_payload(req), "approval": _approval_payload(approval, req)}


def reject_request(session: Session, settings: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("dispatch_request_id") or "").strip()
    approver_user_id = str(payload.get("approver_user_id") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    replay_token = str(payload.get("replay_token") or "").strip()

    req = _find_request(session, request_id)
    if req is None:
        return {"ok": False, "error": "request not found"}
    approval = _find_pending_approval(session, request_id)
    if approval is None:
        return {"ok": False, "error": "pending approval not found"}

    allowed = _json_loads_list(settings.allowed_approver_ids_json)
    if allowed and approver_user_id not in allowed:
        return {"ok": False, "error": "approver user not allowlisted"}

    if _worker_token_hash(replay_token) != approval.replay_token_hash:
        return {"ok": False, "error": "invalid replay token"}

    approval.status = "rejected"
    approval.approver_user_id = approver_user_id
    approval.decision_reason = reason
    approval.decided_at = _utcnow()
    session.add(approval)
    session.commit()

    _set_request_status(session, req, "rejected", error=reason or "approval rejected")
    _create_audit_event(session, audit_id=req.audit_id, dispatch_request_id=req.id, event_type="approval.rejected", actor=approver_user_id or "approver", message="Approval rejected", payload={"reason": reason})
    return {"ok": True, "status": "rejected", "request": _request_payload(req), "approval": _approval_payload(approval, req)}


def policy_evaluate_preview(session: Session, settings: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    requester = payload.get("requester") if isinstance(payload.get("requester"), dict) else {}
    normalized = _normalize_action(payload)
    target_lookup = _build_target_lookup(session, settings)
    target = target_lookup.get(normalized.target) if normalized.target else None
    outcome = evaluate_policy(settings, normalized, requester, target)
    return {
        "action": normalized.__dict__,
        "policy": outcome.__dict__,
        "target": target,
    }


def get_audit(session: Session, audit_id: str) -> dict[str, Any]:
    events = list(session.exec(select(DiscordAuditEvent).where(DiscordAuditEvent.audit_id == audit_id).order_by(DiscordAuditEvent.created_at.asc())).all())
    req = session.exec(select(DiscordDispatchRequest).where(DiscordDispatchRequest.audit_id == audit_id)).first()
    return {
        "ok": bool(events or req),
        "audit_id": audit_id,
        "request": _request_payload(req) if req else None,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "actor": e.actor,
                "message": e.message,
                "payload": _json_loads_dict(e.payload_json),
                "created_at": _to_iso(e.created_at),
            }
            for e in events
        ],
    }


def _worker_row(session: Session, worker_id: str) -> DispatchWorkerHeartbeat | None:
    return session.get(DispatchWorkerHeartbeat, worker_id)


def register_worker(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    worker_id = str(payload.get("worker_id") or "").strip()
    if not worker_id:
        return {"ok": False, "error": "worker_id required"}
    row = _worker_row(session, worker_id)
    if row is None:
        row = DispatchWorkerHeartbeat(id=worker_id)
    row.label = str(payload.get("label") or row.label)
    row.host = str(payload.get("host") or row.host)
    row.capabilities_json = _json_dumps(payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else [])
    row.supports_isolated_execution = bool(payload.get("supports_isolated_execution", row.supports_isolated_execution))
    row.dispatch_enabled = bool(payload.get("dispatch_enabled", row.dispatch_enabled))
    row.auth_key_id = str(payload.get("auth_key_id") or row.auth_key_id)
    row.status = "online"
    row.metadata_json = _json_dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
    row.last_seen_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return {
        "ok": True,
        "worker": {
            "id": row.id,
            "label": row.label,
            "host": row.host,
            "capabilities": _json_loads_list(row.capabilities_json),
            "supports_isolated_execution": row.supports_isolated_execution,
            "dispatch_enabled": row.dispatch_enabled,
            "status": row.status,
            "last_seen_at": _to_iso(row.last_seen_at),
        },
    }


def worker_heartbeat(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    worker_id = str(payload.get("worker_id") or "").strip()
    row = _worker_row(session, worker_id)
    if row is None:
        return {"ok": False, "error": "worker not registered"}
    row.status = str(payload.get("status") or "online")
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    row.metadata_json = _json_dumps(meta)
    row.last_seen_at = _utcnow()
    session.add(row)
    session.commit()
    return {"ok": True, "worker_id": worker_id, "status": row.status, "last_seen_at": _to_iso(row.last_seen_at)}


def _request_matches_worker(req: DiscordDispatchRequest, worker_caps: set[str], supports_isolated: bool) -> bool:
    if req.status != "queued":
        return False
    if req.isolated_required and not supports_isolated:
        return False
    action_caps = set(_ACTION_CAPABILITIES.get(req.action_type, []))
    if not action_caps:
        return True
    return bool(action_caps.intersection(worker_caps))


def worker_poll(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    worker_id = str(payload.get("worker_id") or "").strip()
    row = _worker_row(session, worker_id)
    if row is None:
        return {"ok": False, "error": "worker not registered"}
    if not row.dispatch_enabled:
        return {"ok": False, "error": "worker dispatch disabled"}

    worker_caps = set(str(v) for v in (payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else _json_loads_list(row.capabilities_json)))
    supports_isolated = bool(row.supports_isolated_execution)
    limit = max(1, min(int(payload.get("limit") or 5), 50))

    candidates = list(
        session.exec(select(DiscordDispatchRequest).where(DiscordDispatchRequest.status == "queued").order_by(DiscordDispatchRequest.created_at.asc())).all()
    )
    out: list[dict[str, Any]] = []
    for req in candidates:
        if not _request_matches_worker(req, worker_caps, supports_isolated):
            continue
        req.status = "dispatched"
        req.dispatch_worker_id = worker_id
        req.started_at = _utcnow()
        req.updated_at = _utcnow()
        session.add(req)
        session.commit()
        _create_audit_event(session, audit_id=req.audit_id, dispatch_request_id=req.id, event_type="worker.accepted", actor=worker_id, message="Worker accepted queued request", payload={"worker_caps": sorted(worker_caps)})
        out.append(_request_payload(req))
        if len(out) >= limit:
            break
    row.last_seen_at = _utcnow()
    session.add(row)
    session.commit()
    return {"ok": True, "items": out, "worker_id": worker_id}


def worker_submit_result(session: Session, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = _find_request(session, request_id)
    if req is None:
        return {"ok": False, "error": "request not found"}

    worker_id = str(payload.get("worker_id") or "").strip()
    if req.dispatch_worker_id and worker_id and req.dispatch_worker_id != worker_id:
        return {"ok": False, "error": "worker mismatch"}

    status = str(payload.get("status") or "failed").strip().lower()
    result_json = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    summary = str(payload.get("result_summary") or "")
    error = str(payload.get("error") or "")

    exec_row = DispatchExecutionResult(
        id=_new_id(),
        audit_id=req.audit_id,
        dispatch_request_id=req.id,
        worker_id=worker_id,
        status=status,
        result_summary=summary[:2000],
        result_json=_json_dumps(result_json),
        error=error[:4000],
        created_at=_utcnow(),
    )
    session.add(exec_row)
    session.commit()

    if status in {"succeeded", "success", "ok"}:
        _set_request_status(session, req, "succeeded", result={"summary": summary, "result": result_json})
        _create_audit_event(session, audit_id=req.audit_id, dispatch_request_id=req.id, event_type="dispatch.succeeded", actor=worker_id or "worker", message="Worker finished request successfully", payload={"summary": summary[:800]})
    else:
        _set_request_status(session, req, "failed", error=error or f"worker status {status}", result={"summary": summary, "result": result_json})
        _create_audit_event(session, audit_id=req.audit_id, dispatch_request_id=req.id, event_type="dispatch.failed", actor=worker_id or "worker", message="Worker failed request", payload={"status": status, "error": error[:800]})

    return {"ok": True, "request": _request_payload(req), "execution_result_id": exec_row.id}


def worker_status(session: Session, limit: int = 100) -> dict[str, Any]:
    rows = list(session.exec(select(DispatchWorkerHeartbeat).order_by(DispatchWorkerHeartbeat.last_seen_at.desc())).all())[: max(1, min(limit, 500))]
    return {
        "items": [
            {
                "id": row.id,
                "label": row.label,
                "host": row.host,
                "capabilities": _json_loads_list(row.capabilities_json),
                "supports_isolated_execution": row.supports_isolated_execution,
                "dispatch_enabled": row.dispatch_enabled,
                "status": row.status,
                "last_seen_at": _to_iso(row.last_seen_at),
                "metadata": _json_loads_dict(row.metadata_json),
            }
            for row in rows
        ]
    }


def reindex_memory(session: Session, row: DiscordIntegrationSettings, dry_run: bool = False) -> dict[str, Any]:
    return DiscordMemoryService(row).reindex(session, dry_run=dry_run)


def append_memory_note(session: Session, row: DiscordIntegrationSettings, note: str, *, kind: str, relevance: float, dry_run: bool) -> dict[str, Any]:
    return DiscordMemoryService(row).append_operational_note(session, note=note, kind=kind, relevance=relevance, dry_run=dry_run)


def bootstrap_discord_session(session: Session, row: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    return DiscordSessionService().resolve_session(row, payload)


def resolve_discord_session(session: Session, row: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    return DiscordSessionService().resolve_session(row, payload)


def dispatch_targets(session: Session, row: DiscordIntegrationSettings) -> dict[str, Any]:
    return DiscordDispatchRegistry().list_targets(session, row)


def dispatch_stub(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "accepted": False,
        "phase": "phase2",
        "reason": "Use /api/discord/dispatch for policy-controlled dispatch flow",
        "requested": {"target_id": str(payload.get("target_id") or ""), "action": str(payload.get("action") or "")},
    }


def _persist_probe_status(session: Session, row: DiscordIntegrationSettings, bridge: dict[str, Any]) -> None:
    row.last_status_json = _json_dumps(bridge)
    row.last_error = str(bridge.get("last_error") or bridge.get("error") or "")
    hb = bridge.get("last_heartbeat")
    seen = bridge.get("last_seen")
    try:
        if hb:
            row.last_heartbeat_at = datetime.fromisoformat(str(hb).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    try:
        if seen:
            row.last_seen_at = datetime.fromisoformat(str(seen).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()


async def get_status_payload(session: Session, row: DiscordIntegrationSettings) -> dict[str, Any]:
    bridge = await DiscordBridgeService().check(row)
    _persist_probe_status(session, row, bridge)
    redis = DiscordSessionService().redis_status()
    memory = DiscordMemoryService(row).index_status()
    dispatch = DiscordDispatchRegistry().list_targets(session, row)

    req_counts = {
        "pending_approval": len(list(session.exec(select(DiscordDispatchRequest).where(DiscordDispatchRequest.status == "pending_approval")).all())),
        "queued": len(list(session.exec(select(DiscordDispatchRequest).where(DiscordDispatchRequest.status == "queued")).all())),
        "running": len(list(session.exec(select(DiscordDispatchRequest).where(DiscordDispatchRequest.status.in_(["running", "dispatched"]))).all())),
    }

    env_presence = {
        "discord_token": bool(str(os.getenv("DISCORD_TOKEN", "")).strip()),
        "bridge_base_url": bool(str(os.getenv("DISCORD_BRIDGE_BASE_URL", "")).strip()),
        "bridge_api_key": bool(str(os.getenv("DISCORD_BRIDGE_API_KEY", "")).strip()),
    }
    reasons: list[str] = []
    if not row.enabled:
        reasons.append("Discord integration is disabled in saved settings.")
    if not row.bot_token:
        reasons.append("Bot token is not saved in Dashburg settings.")
    if row.bot_token == "" and env_presence["discord_token"]:
        reasons.append("DISCORD_TOKEN exists in .env but has not been saved into Discord settings yet.")
    if not str(row.bridge_url or "").strip():
        reasons.append("Bridge URL is not configured.")
    elif not bridge.get("reachable"):
        reasons.append(f"Bridge is unreachable at {row.bridge_url}.")
    elif not bridge.get("online"):
        reasons.append(f"Bridge reachable but bot is offline: {str(bridge.get('last_error') or bridge.get('error') or 'no bot heartbeat')}")
    if row.bridge_auth_enabled and not row.bridge_api_key:
        reasons.append("Bridge auth is enabled, but bridge API key is not saved.")
    if row.bridge_auth_enabled and row.bridge_api_key == "" and env_presence["bridge_api_key"]:
        reasons.append("DISCORD_BRIDGE_API_KEY exists in .env but has not been saved into Discord settings yet.")
    if not redis.get("reachable"):
        reasons.append("Redis is unreachable for Discord session state.")
    if not memory.get("healthy"):
        reasons.append("MEM.md indexing source is unavailable.")

    setup_actions: list[str] = []
    if row.bot_token == "" and env_presence["discord_token"]:
        setup_actions.append("Open Discord Control -> Settings and click Save to persist token and allowlists from UI.")
    if not row.enabled:
        setup_actions.append("Enable Discord integration in settings.")
    if row.bridge_auth_enabled and not row.bridge_api_key and env_presence["bridge_api_key"]:
        setup_actions.append("Persist bridge API key in settings, then run Connection Test.")
    if not bridge.get("reachable"):
        setup_actions.append("Start the Discord bridge service and verify /status or /health responds at configured bridge URL.")

    return {
        "settings": settings_to_public(row),
        "overview": {
            "integration_enabled": row.enabled,
            "bot_online": bool(bridge.get("online")),
            "bridge_reachable": bool(bridge.get("reachable")),
            "redis_reachable": bool(redis.get("reachable")),
            "memory_pipeline": "healthy" if memory.get("healthy") else "degraded",
            "dispatch_readiness": "ready" if row.dispatch_enabled and not row.read_only_mode else "restricted",
            "last_heartbeat": _to_iso(row.last_heartbeat_at) or bridge.get("last_heartbeat"),
            "last_seen": _to_iso(row.last_seen_at) or bridge.get("last_seen"),
            "last_error": row.last_error,
            "request_counts": req_counts,
        },
        "diagnostics": {
            "summary": "ok" if not reasons else "action_required",
            "reasons": reasons,
            "next_actions": setup_actions,
            "env_presence": env_presence,
        },
        "bridge": bridge,
        "redis": redis,
        "memory": memory,
        "dispatch": dispatch,
        "workers": worker_status(session, limit=50),
    }


async def run_connectivity_test(session: Session, row: DiscordIntegrationSettings, payload: dict[str, Any]) -> dict[str, Any]:
    bridge = {"ok": None, "skipped": True}
    redis = {"ok": None, "skipped": True}
    memory = {"ok": None, "skipped": True}

    if bool(payload.get("include_bridge", True)):
        bridge = await DiscordBridgeService().check(row)
        _persist_probe_status(session, row, bridge)
    if bool(payload.get("include_redis", True)):
        redis = DiscordSessionService().redis_status()
    if bool(payload.get("include_memory", True)):
        mem = DiscordMemoryService(row).index_status()
        memory = {"ok": bool(mem.get("healthy")), "source_path": mem.get("source_path"), "indexed_section_count": mem.get("indexed_section_count"), "error": "" if mem.get("healthy") else "MEM source unavailable"}

    ok = all(part.get("ok") is True for part in (bridge, redis, memory) if part.get("skipped") is not True)
    return {"ok": ok, "checked_at": _now_iso(), "bridge": bridge, "redis": redis, "memory": memory}
