#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import discord
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _env(name: str, default: str = "") -> str:
    val = os.getenv(name, "").strip()
    if val:
        return val
    return _ENV_FILE.get(name, default).strip() or default


def _id_list(name: str) -> set[str]:
    raw = _env(name, "")
    out: set[str] = set()
    for part in raw.replace(",", " ").split():
        token = "".join(ch for ch in part if ch.isdigit())
        if token:
            out.add(token)
    return out


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    body = None
    req_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _http_any(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any:
    body = None
    req_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw or "{}")
    except Exception:
        return raw


def _json_preview(value: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except Exception:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


def _parse_iso_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _load_env_file(ROOT / ".env")

DISCORD_TOKEN = _env("DISCORD_TOKEN", "")
DASHBURG_BASE = _env("DISCORD_DASHBURG_BASE_URL", "http://127.0.0.1:8321").rstrip("/")
BRIDGE_BIND = _env("DISCORD_BRIDGE_BIND", "127.0.0.1")
BRIDGE_PORT = int(_env("DISCORD_BRIDGE_PORT", "9101") or "9101")
BRIDGE_API_KEY = _env("DISCORD_BRIDGE_API_KEY", _env("DISCORD_BRIDGE_SHARED_KEY", ""))
REMOTEOPS_ADMIN_TOKEN = _env("REMOTEOPS_ADMIN_TOKEN", "")
REMOTEOPS_CLIENT_TOKEN = _env("REMOTEOPS_CLIENT_TOKEN", "")
ALLOWED_USERS = _id_list("DISCORD_ALLOWED_USER_IDS")
ALLOWED_CHANNELS = _id_list("DISCORD_ALLOWED_CHANNEL_IDS")
ALLOWED_GUILDS = _id_list("DISCORD_ALLOWED_GUILD_IDS")
if not ALLOWED_GUILDS and _env("DISCORD_GUILD_ID", ""):
    ALLOWED_GUILDS = {_env("DISCORD_GUILD_ID", "")}

DM_WINDOW_SECONDS = max(60, int(_env("DISCORD_DM_WINDOW_SECONDS", "180") or "180"))
PING_DEFAULT_COUNT = max(1, int(_env("DISCORD_PING_DEFAULT_COUNT", "4") or "4"))
PING_MAX_COUNT = max(PING_DEFAULT_COUNT, int(_env("DISCORD_PING_MAX_COUNT", "10") or "10"))
REPORT_TZ = _env("DISCORD_REPORT_TZ", "America/New_York")

try:
    HTTP_GET_ALLOWLIST = json.loads(_env("DISCORD_HTTP_GET_ALLOWLIST_JSON", "{}") or "{}")
except Exception:
    HTTP_GET_ALLOWLIST = {}
if not isinstance(HTTP_GET_ALLOWLIST, dict):
    HTTP_GET_ALLOWLIST = {}
HTTP_GET_ALLOWLIST = {
    str(k).strip().lower(): str(v).strip()
    for k, v in HTTP_GET_ALLOWLIST.items()
    if str(k).strip() and str(v).strip()
}


STATE: dict[str, Any] = {
    "started_at": _utc_iso(),
    "bot_online": False,
    "connected": False,
    "last_heartbeat": None,
    "last_seen": None,
    "last_error": "",
    "last_command": "",
    "last_command_at": None,
    "last_route": "",
    "dm_sessions_open": 0,
}

DM_CONTEXT: dict[str, dict[str, Any]] = {}
NODE_CACHE: dict[str, Any] = {"nodes": [], "fetched_at": 0.0}
NODE_CACHE_TTL_SECONDS = 20


def _touch_ok() -> None:
    now = _utc_iso()
    STATE["bot_online"] = True
    STATE["connected"] = True
    STATE["last_seen"] = now
    STATE["last_heartbeat"] = now
    STATE["last_error"] = ""


def _touch_err(message: str) -> None:
    STATE["connected"] = False
    STATE["bot_online"] = False
    STATE["last_error"] = str(message)[:2000]
    STATE["last_seen"] = _utc_iso()


def _bridge_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if BRIDGE_API_KEY:
        headers["X-Dashburg-Bridge-Key"] = BRIDGE_API_KEY
    return headers


def _auth_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if REMOTEOPS_ADMIN_TOKEN:
        headers["X-RemoteOps-Admin-Token"] = REMOTEOPS_ADMIN_TOKEN
    elif REMOTEOPS_CLIENT_TOKEN:
        headers["X-RemoteOps-Client-Token"] = REMOTEOPS_CLIENT_TOKEN
    return headers


def _merged_headers(*rows: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        out.update(row)
    return out


def _dispatch_request(
    *,
    action_type: str,
    prompt: str,
    requester: dict[str, Any],
    target: str = "dashburg-memory",
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_type": action_type,
        "target": target,
        "args": args or {},
        "prompt": prompt[:1200],
        "requester": requester,
        "session": {
            "user_id": requester.get("user_id") or "",
            "guild_id": requester.get("guild_id") or "",
            "channel_id": requester.get("channel_id") or "",
        },
    }
    return _http_json(
        "POST",
        f"{DASHBURG_BASE}/api/discord/ingest",
        headers=_bridge_headers(),
        payload=payload,
        timeout=20.0,
    )


def _poll_bridge_request(request_id: str, *, timeout_seconds: int = 25) -> dict[str, Any]:
    if not request_id:
        return {}
    deadline = time.time() + max(2, timeout_seconds)
    while time.time() < deadline:
        out = _http_json(
            "GET",
            f"{DASHBURG_BASE}/api/discord/bridge/requests/{request_id}",
            headers=_bridge_headers(),
            timeout=8.0,
        )
        req = out.get("request") if isinstance(out, dict) else {}
        status = str(req.get("status") or "")
        if status in {"succeeded", "failed", "denied", "rejected", "expired"}:
            return out
        time.sleep(1.0)
    return {}


def _safe_ping_target(value: str) -> str:
    token = str(value or "").strip()
    if not token or len(token) > 253 or token.startswith("-"):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", token):
        return ""
    return token


def _safe_ping_count(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return PING_DEFAULT_COUNT
    try:
        parsed = int(raw)
    except Exception:
        return -1
    if parsed < 1:
        return -1
    return min(parsed, PING_MAX_COUNT)


def _run_ping(target: str, count: int) -> tuple[bool, str]:
    cmd = ["ping", "-c", str(count), "-W", "2", target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(6, count * 3), check=False)
    except Exception as exc:
        return False, f"Ping execution failed: {exc}"
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    summary_lines = [ln for ln in lines if "packets transmitted" in ln or "rtt " in ln]
    snippet = " | ".join((summary_lines or lines[-3:]))[:1400] if lines else ""
    if proc.returncode == 0:
        return True, snippet or f"Ping to {target} succeeded."
    return False, snippet or f"Ping to {target} failed."


def _is_dm_message(message: discord.Message) -> bool:
    return getattr(message, "guild", None) is None


def _is_allowed(message: discord.Message) -> bool:
    uid = str(message.author.id)
    if _is_dm_message(message):
        if ALLOWED_USERS:
            return uid in ALLOWED_USERS
        return False

    cid = str(getattr(message.channel, "id", "") or "")
    gid = str(getattr(message.guild, "id", "") or "")
    if ALLOWED_USERS and uid not in ALLOWED_USERS:
        return False
    if ALLOWED_CHANNELS and cid not in ALLOWED_CHANNELS:
        return False
    if ALLOWED_GUILDS and gid not in ALLOWED_GUILDS:
        return False
    return True


def _requester_from_message(message: discord.Message) -> dict[str, Any]:
    is_dm = _is_dm_message(message)
    return {
        "user_id": str(message.author.id),
        "guild_id": str(getattr(message.guild, "id", "") or ""),
        "channel_id": str(getattr(message.channel, "id", "") or ""),
        "name": str(getattr(message.author, "display_name", message.author.name)),
        "role_ids": [str(role.id) for role in getattr(message.author, "roles", []) if hasattr(role, "id")],
        "is_dm": is_dm,
    }


def _dm_key(requester: dict[str, Any]) -> str:
    return f"{requester.get('user_id','')}:{requester.get('channel_id','dm')}"


def _resolve_dm_session(requester: dict[str, Any]) -> str:
    key = _dm_key(requester)
    now = time.time()
    row = DM_CONTEXT.get(key, {})
    expires_at = float(row.get("expires_at", 0))
    if expires_at <= now:
        session_id = f"discord-dm-{requester.get('user_id','u')}-{int(now)}"
    else:
        session_id = str(row.get("session_id") or f"discord-dm-{requester.get('user_id','u')}-{int(now)}")
    DM_CONTEXT[key] = {
        "session_id": session_id,
        "expires_at": now + DM_WINDOW_SECONDS,
        "last_seen": _utc_iso(),
    }
    STATE["dm_sessions_open"] = sum(1 for v in DM_CONTEXT.values() if float(v.get("expires_at", 0)) > now)
    return session_id


def _cleanup_dm_context() -> None:
    now = time.time()
    dead = [k for k, v in DM_CONTEXT.items() if float(v.get("expires_at", 0)) <= now]
    for key in dead:
        DM_CONTEXT.pop(key, None)
    STATE["dm_sessions_open"] = sum(1 for v in DM_CONTEXT.values() if float(v.get("expires_at", 0)) > now)


def _chat_stream_reply(session_id: str, prompt: str, *, source: str = "discord") -> str:
    url = f"{DASHBURG_BASE}/api/chat/sessions/{urllib.parse.quote(session_id)}/stream"
    headers = _merged_headers(_auth_headers(), {"Content-Type": "application/json", "Accept": "text/event-stream"})
    payload = {
        "content": prompt,
        "source": source,
        "include_memory": True,
        "max_history_messages": 24,
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    chunks: list[str] = []
    current_event = ""
    with urllib.request.urlopen(req, timeout=90) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                continue
            if not line.startswith("data:"):
                continue
            data_text = line.split(":", 1)[1].strip()
            try:
                row = json.loads(data_text)
            except Exception:
                row = {}
            if current_event == "delta":
                piece = str(row.get("text") or "")
                if piece:
                    chunks.append(piece)
            elif current_event == "final":
                msg = row.get("message") if isinstance(row.get("message"), dict) else {}
                final = str(msg.get("content") or "")
                if final:
                    return final[:1800]
            elif current_event == "error":
                raise RuntimeError(str(row.get("error") or "chat stream error"))
    text = "".join(chunks).strip()
    return text[:1800]


def _run_chat_fallback(session_id: str, prompt: str, requester: dict[str, Any]) -> str:
    memory_brief_text = ""
    try:
        mem = _http_json(
            "POST",
            f"{DASHBURG_BASE}/api/memory/brief",
            headers=_auth_headers(),
            payload={"query": prompt, "max_chars": 1200},
            timeout=12.0,
        )
        memory_brief_text = str(mem.get("brief") or "").strip()
    except Exception:
        memory_brief_text = ""

    grounded_prompt = prompt
    if memory_brief_text:
        grounded_prompt = f"{prompt}\n\nUse these memory facts when answering:\n{memory_brief_text}"

    try:
        out = _chat_stream_reply(session_id, grounded_prompt, source="discord")
        if out:
            return out
    except Exception:
        pass

    out = _dispatch_request(
        action_type="session.ask",
        prompt=grounded_prompt,
        requester=requester,
        target="dashburg-memory",
        args={"query": grounded_prompt},
    )
    req = out.get("request") if isinstance(out, dict) else {}
    status = str(out.get("status") or req.get("status") or "unknown")
    if status == "queued" and isinstance(req, dict) and req.get("id"):
        polled = _poll_bridge_request(str(req.get("id")))
        if polled:
            req = polled.get("request") if isinstance(polled, dict) else {}
            status = str(req.get("status") or status)
    result = req.get("result") if isinstance(req, dict) and isinstance(req.get("result"), dict) else {}
    summary = str(result.get("summary") or result.get("answer") or result.get("error") or "")
    if summary:
        return summary[:1800]
    return f"Status: {status}. No summary returned yet."


def _fetch_nodes_health() -> list[dict[str, Any]]:
    out = _http_json("GET", f"{DASHBURG_BASE}/api/remote/nodes/health", headers=_auth_headers(), timeout=10.0)
    rows = out.get("nodes") if isinstance(out.get("nodes"), list) else []
    return [r for r in rows if isinstance(r, dict)]


def _fetch_nodes() -> list[dict[str, Any]]:
    out = _http_any("GET", f"{DASHBURG_BASE}/api/remote/nodes", headers=_auth_headers(), timeout=10.0)
    if isinstance(out, list):
        return [r for r in out if isinstance(r, dict)]
    return []


def _fetch_nodes_cached() -> list[dict[str, Any]]:
    now = time.time()
    if (now - float(NODE_CACHE.get("fetched_at", 0.0))) <= NODE_CACHE_TTL_SECONDS and isinstance(NODE_CACHE.get("nodes"), list):
        return [r for r in NODE_CACHE.get("nodes", []) if isinstance(r, dict)]
    rows = _fetch_nodes()
    NODE_CACHE["nodes"] = rows
    NODE_CACHE["fetched_at"] = now
    return rows


def _extract_host(base_url: str) -> str:
    text = str(base_url or "").strip()
    if not text:
        return ""
    try:
        return str(urlparse(text).hostname or text)
    except Exception:
        return text


def _node_label_map() -> dict[str, str]:
    rows = _fetch_nodes_cached()
    out: dict[str, str] = {}
    for row in rows:
        node_id = str(row.get("id") or "").strip()
        if not node_id:
            continue
        label = str(row.get("label") or node_id).strip()
        out[node_id] = label
    return out


def _find_node_from_text(text: str) -> str:
    query = str(text or "").strip().lower()
    if not query:
        return ""
    rows = _fetch_nodes_cached()
    candidates: list[tuple[int, str]] = []
    for row in rows:
        node_id = str(row.get("id") or "").strip()
        label = str(row.get("label") or "").strip()
        for token in (node_id, label):
            t = token.lower()
            if t and t in query:
                candidates.append((len(t), node_id))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _build_nodes_summary_text() -> str:
    health_rows = _fetch_nodes_health()
    labels = _node_label_map()
    total = len(health_rows)
    if total == 0:
        return "Node status unavailable."

    buckets = {"healthy": 0, "slow": 0, "degraded": 0, "down": 0, "unknown": 0}
    problem_nodes: list[str] = []
    for row in health_rows:
        status = str(row.get("status") or "unknown").strip().lower()
        if status not in buckets:
            status = "unknown"
        buckets[status] += 1
        if status in {"degraded", "down", "unknown"} or not bool(row.get("ok")):
            nid = str(row.get("node_id") or "")
            label = labels.get(nid, nid or "unknown")
            err = str(row.get("error") or "").strip()
            if err:
                problem_nodes.append(f"{label} ({status}: {err[:120]})")
            else:
                problem_nodes.append(f"{label} ({status})")

    summary = (
        f"Nodes: total={total}, healthy={buckets['healthy']}, slow={buckets['slow']}, "
        f"degraded={buckets['degraded']}, down={buckets['down']}, unknown={buckets['unknown']}"
    )
    if problem_nodes:
        return summary + "\nIssues: " + "; ".join(problem_nodes[:8])
    return summary + "\nAll nodes look healthy."


def _node_status_by_name(name: str) -> str:
    token = str(name or "").strip().lower()
    if not token:
        return "Node name is required."
    health_rows = _fetch_nodes_health()
    labels = _node_label_map()
    if not health_rows:
        return "Node status unavailable."
    candidates: list[dict[str, Any]] = []
    for row in health_rows:
        nid = str(row.get("node_id") or "")
        label = labels.get(nid, nid).lower()
        if token == nid.lower() or token == label:
            candidates = [row]
            break
        if token in nid.lower() or token in label:
            candidates.append(row)
    if not candidates:
        known = ", ".join(sorted([v for v in labels.values()])[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    row = candidates[0]
    nid = str(row.get("node_id") or "")
    label = labels.get(nid, nid or name)
    status = str(row.get("status") or "unknown").lower()
    ok = bool(row.get("ok"))
    latency = row.get("latency_ms")
    err = str(row.get("error") or "").strip()
    prefix = "online" if ok and status in {"healthy", "slow"} else "offline"
    details = f"status={status}"
    if latency is not None:
        details += f", latency={latency}ms"
    if err:
        details += f", error={err[:180]}"
    return f"{label}: {prefix} ({details})"


def _video_count_today_text() -> str:
    rows = _http_any("GET", f"{DASHBURG_BASE}/api/viralvideo/runs", headers=_auth_headers(), timeout=12.0)
    if not isinstance(rows, list):
        return "Video run dataset unavailable."
    tz = ZoneInfo(REPORT_TZ)
    now_local = datetime.now(tz)
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    terminal = {"succeeded", "success", "completed", "failed", "error", "canceled", "cancelled"}
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status not in terminal:
            continue
        finished = _parse_iso_dt(row.get("finished_at"))
        if not finished:
            continue
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        local = finished.astimezone(tz)
        if day_start <= local <= day_end:
            count += 1
    return f"Videos finished today ({REPORT_TZ}): {count}"


def _node_runtime_by_name(name: str) -> str:
    token = str(name or "").strip().lower()
    if not token:
        return "Node name is required."
    monitor = _http_json(
        "GET",
        f"{DASHBURG_BASE}/api/remote/nodes/host-monitor?include_processes=true&include_gpu_processes=true",
        headers=_auth_headers(),
        timeout=12.0,
    )
    rows = monitor.get("nodes") if isinstance(monitor.get("nodes"), list) else []
    if not rows:
        return "Host-monitor data unavailable."

    match: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("node_id") or "").lower()
        label = str(row.get("label") or "").lower()
        if token == node_id or token == label or token in node_id or token in label:
            match = row
            break
    if not match:
        known = ", ".join(sorted({str(r.get("label") or r.get("node_id") or "") for r in rows if isinstance(r, dict)})[:12])
        return f"Node '{name}' not found in host monitor. Known nodes: {known}"

    label = str(match.get("label") or match.get("node_id") or name)
    status = str(match.get("status") or "unknown")
    ok = bool(match.get("ok"))
    latency = match.get("latency_ms")
    payload = match.get("payload") if isinstance(match.get("payload"), dict) else {}
    top = payload.get("top_processes") if isinstance(payload.get("top_processes"), list) else []
    proc_lines: list[str] = []
    for row in top[:6]:
        if not isinstance(row, dict):
            continue
        cmd = str(row.get("command") or "").strip()
        if len(cmd) > 110:
            cmd = cmd[:110] + "..."
        proc_lines.append(
            f"pid={row.get('pid')} cpu={row.get('cpu_percent')}% mem={row.get('mem_percent')}% cmd={cmd}"
        )
    prefix = "online" if ok else "offline"
    head = f"{label}: {prefix} (status={status}"
    if latency is not None:
        head += f", latency={latency}ms"
    head += ")"
    if proc_lines:
        return head + "\nTop processes:\n- " + "\n- ".join(proc_lines)
    return head + "\nNo process list returned."


def _node_monitor_by_name(name: str, *, include_processes: bool) -> dict[str, Any] | None:
    token = str(name or "").strip().lower()
    if not token:
        return None
    monitor = _http_json(
        "GET",
        f"{DASHBURG_BASE}/api/remote/nodes/host-monitor?include_processes={'true' if include_processes else 'false'}&include_gpu_processes=true",
        headers=_auth_headers(),
        timeout=12.0,
    )
    rows = monitor.get("nodes") if isinstance(monitor.get("nodes"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("node_id") or "").lower()
        label = str(row.get("label") or "").lower()
        if token == node_id or token == label or token in node_id or token in label:
            return row
    return None


def _node_memory_by_name(name: str) -> str:
    row = _node_monitor_by_name(name, include_processes=False)
    if not row:
        known = ", ".join(sorted(set(_node_label_map().values()))[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    label = str(row.get("label") or row.get("node_id") or name)
    status = str(row.get("status") or "unknown")
    ok = bool(row.get("ok"))
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    swap = payload.get("swap") if isinstance(payload.get("swap"), dict) else {}
    latency = row.get("latency_ms")

    prefix = "online" if ok else "offline"
    head = f"{label}: {prefix} (status={status}"
    if latency is not None:
        head += f", latency={latency}ms"
    head += ")"
    mem_line = f"RAM: used={memory.get('used_gib')} GiB / total={memory.get('total_gib')} GiB ({memory.get('used_percent')}%)"
    swap_line = f"Swap: used={swap.get('used_gib')} GiB / total={swap.get('total_gib')} GiB ({swap.get('used_percent')}%)"
    return f"{head}\n{mem_line}\n{swap_line}"


def _node_cpu_by_name(name: str) -> str:
    row = _node_monitor_by_name(name, include_processes=False)
    if not row:
        known = ", ".join(sorted(set(_node_label_map().values()))[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    label = str(row.get("label") or row.get("node_id") or name)
    status = str(row.get("status") or "unknown")
    ok = bool(row.get("ok"))
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    cpu = payload.get("cpu") if isinstance(payload.get("cpu"), dict) else {}
    latency = row.get("latency_ms")
    prefix = "online" if ok else "offline"
    head = f"{label}: {prefix} (status={status}"
    if latency is not None:
        head += f", latency={latency}ms"
    head += ")"
    return (
        f"{head}\n"
        f"CPU: usage={cpu.get('usage_percent')}% "
        f"load1={cpu.get('load1')} load5={cpu.get('load5')} load15={cpu.get('load15')}"
    )


def _node_disk_by_name(name: str) -> str:
    row = _node_monitor_by_name(name, include_processes=False)
    if not row:
        known = ", ".join(sorted(set(_node_label_map().values()))[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    label = str(row.get("label") or row.get("node_id") or name)
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else {}
    return (
        f"{label}: disk usage\n"
        f"Mount {disk.get('mount')}: used={disk.get('used_gib')} GiB / total={disk.get('total_gib')} GiB ({disk.get('used_percent')}%)"
    )


def _node_gpu_by_name(name: str) -> str:
    row = _node_monitor_by_name(name, include_processes=False)
    if not row:
        known = ", ".join(sorted(set(_node_label_map().values()))[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    label = str(row.get("label") or row.get("node_id") or name)
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    gpus = payload.get("gpus") if isinstance(payload.get("gpus"), list) else []
    if not gpus:
        return f"{label}: no GPUs reported."
    lines = [f"{label}: GPU status"]
    for gpu in gpus[:4]:
        if not isinstance(gpu, dict):
            continue
        lines.append(
            f"- {gpu.get('name') or gpu.get('id')}: util={gpu.get('utilization_gpu')}% "
            f"mem={gpu.get('memory_used_mib')}/{gpu.get('memory_total_mib')} MiB temp={gpu.get('temperature')}C"
        )
    return "\n".join(lines)


def _node_service_by_name(name: str, service: str) -> str:
    row = _node_monitor_by_name(name, include_processes=False)
    if not row:
        known = ", ".join(sorted(set(_node_label_map().values()))[:12])
        return f"Node '{name}' not found. Known nodes: {known}"
    label = str(row.get("label") or row.get("node_id") or name)
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    service_key = str(service or "").strip().lower()
    if service_key in {"ollama", "comfyui", "comfy", "comfy-ui"}:
        if service_key.startswith("comfy"):
            comfy = payload.get("comfyui") if isinstance(payload.get("comfyui"), dict) else {}
            return (
                f"{label}: comfyui status={comfy.get('status')} "
                f"reachable={comfy.get('reachable')} listening={comfy.get('listening_8188')}"
            )
        ollama = payload.get("ollama") if isinstance(payload.get("ollama"), dict) else {}
        return (
            f"{label}: ollama status={ollama.get('status')} "
            f"reachable={ollama.get('reachable')} listening={ollama.get('listening_11434')} "
            f"models={ollama.get('model_count')}"
        )
    return f"Unsupported service '{service}'. Try ollama or comfyui."


def _node_location_by_name(name: str) -> str:
    token = str(name or "").strip().lower()
    if not token:
        return "Node name is required."
    rows = _fetch_nodes_cached()
    match: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        node_id = str(row.get("id") or "").lower()
        label = str(row.get("label") or "").lower()
        if token == node_id or token == label or token in node_id or token in label:
            match = row
            break
    if not match:
        known = ", ".join(sorted({str(r.get("label") or r.get("node_id") or "") for r in rows if isinstance(r, dict)})[:12])
        return f"Node '{name}' not found. Known nodes: {known}"

    label = str(match.get("label") or match.get("id") or name)
    node_id = str(match.get("id") or "")
    base_url = str(match.get("base_url") or "")
    host = _extract_host(base_url)
    repos = match.get("allowed_repos") if isinstance(match.get("allowed_repos"), list) else []
    repos_text = ", ".join(str(r) for r in repos[:5]) if repos else "(none)"
    return f"{label} ({node_id})\nHost: {host}\nRunner: {base_url}\nAllowed repos: {repos_text}"


def _nodes_inventory_text() -> str:
    nodes = _fetch_nodes_cached()
    health_rows = _fetch_nodes_health()
    health_by_id = {str(r.get("node_id") or ""): r for r in health_rows if isinstance(r, dict)}
    if not nodes:
        return "No nodes found."
    lines = ["Dashburg nodes:"]
    for row in nodes[:20]:
        node_id = str(row.get("id") or "")
        label = str(row.get("label") or node_id)
        host = _extract_host(str(row.get("base_url") or ""))
        h = health_by_id.get(node_id, {})
        status = str(h.get("status") or "unknown")
        lines.append(f"- {label} ({node_id}) host={host} status={status}")
    return "\n".join(lines)


def _nodes_down_text() -> str:
    rows = _fetch_nodes_health()
    if not rows:
        return "Node status unavailable."
    labels = _node_label_map()
    down: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").lower()
        ok = bool(row.get("ok"))
        if ok and status in {"healthy", "slow"}:
            continue
        node_id = str(row.get("node_id") or "")
        down.append(f"{labels.get(node_id, node_id)}({status or 'unknown'})")
    if not down:
        return "No nodes are currently down."
    return "Nodes currently down/degraded: " + ", ".join(down[:20])


def _ops_help_text() -> str:
    return (
        "Try questions like:\n"
        "- What is the status of the nodes?\n"
        "- Which nodes are down?\n"
        "- What is the ram usage on renderserver?\n"
        "- What is the cpu usage on aitts?\n"
        "- What is disk usage on staging-backend?\n"
        "- Is ollama running on aitts?\n"
        "- Is comfyui running on renderserver?\n"
        "- What is running on node aitts?\n"
        "- Where is node topicsite?\n"
        "- How many videos were created today?\n"
        "- ping 192.168.1.1 5"
    )


def _build_status_report() -> str:
    data = _http_json("GET", f"{DASHBURG_BASE}/api/discord/status", headers=_auth_headers(), timeout=10.0)
    ov = data.get("overview") if isinstance(data, dict) else {}
    line1 = (
        f"Integration={ov.get('integration_enabled')} "
        f"Bot={ov.get('bot_online')} "
        f"Bridge={ov.get('bridge_reachable')} "
        f"Redis={ov.get('redis_reachable')}"
    )
    line2 = _build_nodes_summary_text()
    return line1 + "\n" + line2


def _safe_alias(alias: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", str(alias or "").lower())


def _run_alias_get(alias: str) -> str:
    key = _safe_alias(alias)
    if not key:
        return "Usage: provide an endpoint alias."
    url = HTTP_GET_ALLOWLIST.get(key)
    if not url:
        known = ", ".join(sorted(HTTP_GET_ALLOWLIST.keys())[:20]) or "(none configured)"
        return f"Alias '{alias}' is not allowlisted. Known aliases: {known}"
    try:
        out = _http_any("GET", url, headers=_auth_headers(), timeout=12.0)
    except Exception as exc:
        return f"Alias GET failed for '{alias}': {exc}"
    return f"{alias}: {_json_preview(out)}"


def _route_nl(text: str) -> tuple[str, dict[str, str]]:
    lower = str(text or "").strip().lower()
    if not lower:
        return ("none", {})

    m = re.search(r"\bping\s+([a-z0-9_.:-]+)(?:\s+(\d{1,3}))?\b", lower)
    if m:
        return ("ping", {"host": m.group(1), "count": m.group(2) or ""})

    if ("status" in lower and "node" in lower) or "how is the dashburg nodes" in lower or "how are the dashburg nodes" in lower:
        return ("nodes_summary", {})

    if ("what nodes" in lower and ("online" in lower or "have" in lower or "exist" in lower)) or "list nodes" in lower:
        return ("nodes_inventory", {})

    if ("nodes are down" in lower) or ("which nodes are down" in lower) or ("down nodes" in lower):
        return ("nodes_down", {})

    m = re.search(r"\bis\s+([a-z0-9_-]+)\s+online\b", lower)
    if m:
        return ("node_check", {"name": m.group(1)})

    m = re.search(r"\b(?:cpu|load)\s+(?:usage|use|used)?\s*(?:on|for|in)?\s*(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_cpu", {"name": m.group(1)})

    m = re.search(r"\b(?:ram|memory)\s+(?:usage|use|used)\s+(?:on|for)\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_memory", {"name": m.group(1)})

    m = re.search(r"\bhow\s+much\s+(?:ram|memory)\s+(?:is\s+)?(?:on|in)\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_memory", {"name": m.group(1)})

    m = re.search(r"\b(?:what(?:'s| is)?\s+running\s+on\s+(?:node\s+)?)\s*([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_runtime", {"name": m.group(1)})

    m = re.search(r"\b(?:services|processes)\s+(?:on|for)\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_runtime", {"name": m.group(1)})

    m = re.search(r"\bdisk\s+(?:usage|use|used|space)\s+(?:on|for)\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_disk", {"name": m.group(1)})

    m = re.search(r"\bgpu\s+(?:status|usage|utilization)?\s*(?:on|for)?\s*(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_gpu", {"name": m.group(1)})

    m = re.search(r"\bis\s+(?:ollama|comfyui|comfy)\s+(?:running|online|up)\s+on\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        svc = "ollama" if "ollama" in lower else "comfyui"
        return ("node_service", {"name": m.group(1), "service": svc})

    m = re.search(r"\bwhere\s+is\s+(?:node\s+)?([a-z0-9_-]+)\b", lower)
    if m:
        return ("node_location", {"name": m.group(1)})

    if "what can you do" in lower or "help" == lower or "help me" in lower or "what can i ask" in lower:
        return ("ops_help", {})

    if ("cpu" in lower or "ram" in lower or "memory" in lower or "disk" in lower or "gpu" in lower or "running on" in lower):
        guessed = _find_node_from_text(lower)
        if guessed:
            if "cpu" in lower or "load" in lower:
                return ("node_cpu", {"name": guessed})
            if "ram" in lower or "memory" in lower:
                return ("node_memory", {"name": guessed})
            if "disk" in lower or "space" in lower:
                return ("node_disk", {"name": guessed})
            if "gpu" in lower:
                return ("node_gpu", {"name": guessed})
            return ("node_runtime", {"name": guessed})

    if "how many videos" in lower and "today" in lower:
        return ("video_count_today", {})

    m = re.search(r"\b(?:endpoint|alias)\s+([a-z0-9_-]+)\b", lower)
    if m and ("check" in lower or "get" in lower or "status" in lower):
        return ("alias_get", {"alias": m.group(1)})

    return ("chat_fallback", {})


def _run_intent(route: str, args: dict[str, str], requester: dict[str, Any], *, session_id: str, original_text: str) -> str:
    if route == "ping":
        host = _safe_ping_target(args.get("host", ""))
        count = _safe_ping_count(args.get("count", ""))
        if not host:
            return "Usage: ping <host-or-ip> [count]"
        if count < 1:
            return f"Invalid ping count. Use 1-{PING_MAX_COUNT}."
        ok, summary = _run_ping(host, count)
        prefix = "Ping OK" if ok else "Ping failed"
        return f"{prefix}: {host} ({count} packets)\n{summary}"
    if route == "nodes_summary":
        return _build_nodes_summary_text()
    if route == "node_check":
        return _node_status_by_name(args.get("name", ""))
    if route == "node_cpu":
        return _node_cpu_by_name(args.get("name", ""))
    if route == "node_memory":
        return _node_memory_by_name(args.get("name", ""))
    if route == "node_runtime":
        return _node_runtime_by_name(args.get("name", ""))
    if route == "node_disk":
        return _node_disk_by_name(args.get("name", ""))
    if route == "node_gpu":
        return _node_gpu_by_name(args.get("name", ""))
    if route == "node_service":
        return _node_service_by_name(args.get("name", ""), args.get("service", ""))
    if route == "node_location":
        return _node_location_by_name(args.get("name", ""))
    if route == "nodes_inventory":
        return _nodes_inventory_text()
    if route == "nodes_down":
        return _nodes_down_text()
    if route == "ops_help":
        return _ops_help_text()
    if route == "video_count_today":
        return _video_count_today_text()
    if route == "alias_get":
        return _run_alias_get(args.get("alias", ""))
    return _run_chat_fallback(session_id=session_id, prompt=original_text, requester=requester)


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
CLIENT = discord.Client(intents=intents)


@CLIENT.event
async def on_ready() -> None:
    _touch_ok()


@CLIENT.event
async def on_disconnect() -> None:
    _touch_err("discord client disconnected")


@CLIENT.event
async def on_error(event_method: str, *args: Any, **kwargs: Any) -> None:
    _touch_err(f"discord event error: {event_method}")


async def _handle_dash_command(message: discord.Message, command: str, arg: str, requester: dict[str, Any]) -> None:
    if command == "ping":
        pieces = arg.split()
        host = _safe_ping_target(pieces[0] if pieces else "")
        count = _safe_ping_count(pieces[1] if len(pieces) > 1 else "")
        if not host:
            await message.reply(f"Usage: /dash ping <host-or-ip> [count 1-{PING_MAX_COUNT}]")
            return
        if count < 1:
            await message.reply(f"Invalid ping count. Use 1-{PING_MAX_COUNT}.")
            return
        ok, summary = _run_ping(host, count)
        prefix = "Ping OK" if ok else "Ping failed"
        await message.reply(f"{prefix}: {host} ({count} packets)\n{summary}")
        return

    if command == "hello":
        await message.reply("Dashburg bridge online.")
        return

    if command == "status":
        await message.reply(_build_status_report())
        return

    if command == "get":
        if not arg.strip():
            await message.reply("Usage: /dash get <alias>")
            return
        await message.reply(_run_alias_get(arg.strip().split()[0]))
        return

    if command == "ask":
        if not arg:
            await message.reply("Usage: /dash ask <question>")
            return
        session_id = f"discord-{requester.get('guild_id') or 'dm'}-{requester.get('channel_id') or 'dm'}-{requester.get('user_id')}"
        out = _run_chat_fallback(session_id=session_id, prompt=arg, requester=requester)
        await message.reply(out[:1800])
        return

    await message.reply("Commands: `/dash ping <host> [count]`, `/dash status`, `/dash ask <question>`, `/dash get <alias>`")


async def _handle_dm_text(message: discord.Message, content: str, requester: dict[str, Any]) -> None:
    session_id = _resolve_dm_session(requester)
    route, args = _route_nl(content)
    STATE["last_route"] = route
    reply = _run_intent(route, args, requester, session_id=session_id, original_text=content)
    await message.reply(reply[:1800] if reply else "No response generated.")


@CLIENT.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    _cleanup_dm_context()
    if not _is_allowed(message):
        return

    content = str(message.content or "").strip()
    if not content:
        return

    _touch_ok()
    STATE["last_command"] = content[:240]
    STATE["last_command_at"] = _utc_iso()
    requester = _requester_from_message(message)
    is_dm = bool(requester.get("is_dm"))

    try:
        if content.startswith("/dash ") or content.startswith("!dash "):
            parts = content.split(maxsplit=2)
            command = parts[1].lower() if len(parts) > 1 else "help"
            arg = parts[2].strip() if len(parts) > 2 else ""
            STATE["last_route"] = f"command:{command}"
            await _handle_dash_command(message, command, arg, requester)
            return

        if is_dm:
            await _handle_dm_text(message, content, requester)
            return

    except urllib.error.HTTPError as exc:
        _touch_err(f"http error {exc.code}")
        await message.reply(f"Bridge request failed with HTTP {exc.code}.")
    except Exception as exc:  # pragma: no cover
        _touch_err(str(exc))
        await message.reply("Bridge failed to process command.")


APP = FastAPI(title="Dashburg Discord Bridge", version="0.2.0")


@APP.get("/health")
async def health() -> JSONResponse:
    _touch_ok() if CLIENT.is_ready() else None
    return JSONResponse(
        {
            "ok": True,
            "status": "healthy" if CLIENT.is_ready() else "starting",
            "online": bool(CLIENT.is_ready()),
            "bot_online": bool(CLIENT.is_ready()),
            "last_heartbeat": STATE.get("last_heartbeat"),
            "last_seen": STATE.get("last_seen"),
            "last_error": STATE.get("last_error", ""),
        }
    )


@APP.get("/status")
async def status() -> JSONResponse:
    _touch_ok() if CLIENT.is_ready() else None
    return JSONResponse(
        {
            "ok": True,
            "status": "online" if CLIENT.is_ready() else "starting",
            "online": bool(CLIENT.is_ready()),
            "bot_online": bool(CLIENT.is_ready()),
            "last_heartbeat": STATE.get("last_heartbeat"),
            "last_seen": STATE.get("last_seen"),
            "last_error": STATE.get("last_error", ""),
            "metrics": {
                "last_command": STATE.get("last_command"),
                "last_command_at": STATE.get("last_command_at"),
                "last_route": STATE.get("last_route"),
                "dm_sessions_open": STATE.get("dm_sessions_open"),
            },
        }
    )


def _run_discord() -> None:
    if not DISCORD_TOKEN:
        _touch_err("DISCORD_TOKEN missing")
        return
    try:
        asyncio.run(CLIENT.start(DISCORD_TOKEN))
    except Exception as exc:  # pragma: no cover
        _touch_err(str(exc))


def main() -> None:
    thread = threading.Thread(target=_run_discord, daemon=True)
    thread.start()

    config = uvicorn.Config(APP, host=BRIDGE_BIND, port=BRIDGE_PORT, log_level="info")
    server = uvicorn.Server(config)
    while not server.started and thread.is_alive():
        time.sleep(0.05)
        break
    server.run()


if __name__ == "__main__":
    main()
