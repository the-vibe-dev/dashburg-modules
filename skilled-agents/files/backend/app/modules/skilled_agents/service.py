from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlencode, urlsplit

DEFAULT_SKILLED_AGENTS_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_MEMORY_NFS_PATH = "/srv/dashburg/shared/MEM.md"
DEFAULT_MEMORY_LOCAL_PATH = "~/MEM.md"
DEFAULT_KNOWLEDGE_API_URL = "http://127.0.0.1:8720"


class SkilledAgentsProxyError(Exception):
    def __init__(self, message: str, upstream_status: int | None = None, upstream_body: Any | None = None):
        super().__init__(message)
        self.message = message
        self.upstream_status = upstream_status
        self.upstream_body = upstream_body


class SkilledAgentsProxyService:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        connect_timeout: float = 2.0,
        read_timeout: float = 12.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = (api_key or "").strip()
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._memory_cache: dict[str, Any] = {"loaded_at": 0.0, "source": "none", "content": ""}

    def memory_context_enabled(self) -> bool:
        return str(os.getenv("SKILLED_AGENTS_MEMORY_CONTEXT_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}

    def _memory_source_mode(self) -> str:
        mode = str(os.getenv("SKILLED_AGENTS_MEMORY_CONTEXT_SOURCE", "nfs_then_home_then_knowledge")).strip().lower()
        return mode or "nfs_then_home_then_knowledge"

    def _memory_cache_ttl_seconds(self) -> float:
        raw = str(os.getenv("SKILLED_AGENTS_MEMORY_CONTEXT_CACHE_TTL_SECONDS", "20")).strip()
        try:
            return max(1.0, float(raw))
        except ValueError:
            return 20.0

    def _memory_max_chars(self) -> int:
        raw = str(os.getenv("SKILLED_AGENTS_MEMORY_CONTEXT_MAX_CHARS", "6000")).strip()
        try:
            return max(500, int(raw))
        except ValueError:
            return 6000

    def _memory_nfs_path(self) -> Path:
        path = str(os.getenv("SKILLED_AGENTS_MEMORY_NFS_PATH", DEFAULT_MEMORY_NFS_PATH)).strip()
        return Path(path or DEFAULT_MEMORY_NFS_PATH)

    def _memory_local_path(self) -> Path:
        path = str(os.getenv("SKILLED_AGENTS_MEMORY_LOCAL_PATH", DEFAULT_MEMORY_LOCAL_PATH)).strip()
        return Path(path or DEFAULT_MEMORY_LOCAL_PATH).expanduser()

    def _knowledge_api_url(self) -> str:
        return str(os.getenv("KNOWLEDGE_API_URL", DEFAULT_KNOWLEDGE_API_URL)).strip() or DEFAULT_KNOWLEDGE_API_URL

    def _knowledge_api_token(self) -> str:
        return str(os.getenv("KNOWLEDGE_API_TOKEN", "")).strip()

    def _knowledge_query(self) -> str:
        return str(os.getenv("SKILLED_AGENTS_MEMORY_CONTEXT_QUERY", "shared intelligence memory process")).strip() or "shared intelligence memory process"

    def _load_memory_from_nfs(self) -> tuple[str, str]:
        path = self._memory_nfs_path()
        if not path.exists() or not path.is_file():
            return "nfs_missing", ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return "nfs_error", ""
        return ("nfs", text)

    def _load_memory_from_home(self) -> tuple[str, str]:
        path = self._memory_local_path()
        if not path.exists() or not path.is_file():
            return "home_missing", ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return "home_error", ""
        return ("home", text)

    def _load_memory_from_knowledge_api(self) -> tuple[str, str]:
        parsed = urlsplit(self._knowledge_api_url().rstrip("/"))
        if not parsed.scheme or not parsed.hostname:
            return "knowledge_url_invalid", ""
        conn: HTTPConnection | HTTPSConnection
        if parsed.scheme == "https":
            conn = HTTPSConnection(parsed.hostname, port=parsed.port or 443, timeout=self._connect_timeout)
        else:
            conn = HTTPConnection(parsed.hostname, port=parsed.port or 80, timeout=self._connect_timeout)
        query_path = f"{parsed.path.rstrip('/')}/search" if parsed.path else "/search"
        body = json.dumps(
            {
                "query": self._knowledge_query(),
                "filters": {
                    "record_types": ["summary_note", "platform_playbook", "qa_rule"],
                    "topic": "cluster_memory",
                },
                "limit": 1,
            }
        ).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = self._knowledge_api_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-API-Key"] = token
        try:
            conn.request("POST", query_path, body=body, headers=headers)
            if conn.sock is not None:
                conn.sock.settimeout(self._read_timeout)
            response = conn.getresponse()
            raw = response.read().decode("utf-8", errors="replace")
        except Exception:
            return "knowledge_unavailable", ""
        finally:
            conn.close()
        if response.status >= 400:
            return f"knowledge_http_{response.status}", ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return "knowledge_parse_error", ""
        rows = payload.get("items") if isinstance(payload.get("items"), list) else payload.get("results")
        if not isinstance(rows, list) or not rows:
            return "knowledge_empty", ""
        row = rows[0] if isinstance(rows[0], dict) else {}
        content = str(row.get("content") or row.get("summary") or row.get("title") or "").strip()
        return ("knowledge_api", content)

    def get_cluster_memory_context(self, force_refresh: bool = False) -> dict[str, Any]:
        if not self.memory_context_enabled():
            return {"enabled": False, "source": "disabled", "content": ""}
        now = time.time()
        if not force_refresh and now - float(self._memory_cache.get("loaded_at") or 0.0) <= self._memory_cache_ttl_seconds():
            return {
                "enabled": True,
                "source": str(self._memory_cache.get("source") or "none"),
                "content": str(self._memory_cache.get("content") or ""),
            }
        source_mode = self._memory_source_mode()
        loader_order = {
            "nfs": [self._load_memory_from_nfs],
            "home": [self._load_memory_from_home],
            "knowledge": [self._load_memory_from_knowledge_api],
            "nfs_then_home": [self._load_memory_from_nfs, self._load_memory_from_home],
            "home_then_nfs": [self._load_memory_from_home, self._load_memory_from_nfs],
            "nfs_then_knowledge": [self._load_memory_from_nfs, self._load_memory_from_knowledge_api],
            "nfs_then_home_then_knowledge": [self._load_memory_from_nfs, self._load_memory_from_home, self._load_memory_from_knowledge_api],
            "knowledge_then_nfs": [self._load_memory_from_knowledge_api, self._load_memory_from_nfs],
        }.get(source_mode, [self._load_memory_from_nfs, self._load_memory_from_home, self._load_memory_from_knowledge_api])
        source = "none"
        content = ""
        for loader in loader_order:
            source, content = loader()
            if content:
                break
        content = content[: self._memory_max_chars()].strip()
        self._memory_cache = {"loaded_at": now, "source": source, "content": content}
        return {"enabled": True, "source": source, "content": content}

    def inject_cluster_memory_context(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = dict(payload or {})
        ctx = self.get_cluster_memory_context()
        marker = "[CLUSTER MEMORY CONTEXT]"
        context_text = str(ctx.get("content") or "").strip()
        data["memory_context"] = {
            "enabled": bool(ctx.get("enabled")),
            "source": str(ctx.get("source") or "none"),
            "content": context_text,
        }
        if not context_text:
            return data
        preamble = f"{marker}\n{context_text}\n[/CLUSTER MEMORY CONTEXT]\n\n"
        for key in ("system_prompt", "instructions", "prompt", "task_prompt"):
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            if marker in value:
                continue
            data[key] = f"{preamble}{value}"
        return data

    def _request_sync(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        parsed = urlsplit(self._base_url)
        if not parsed.scheme or not parsed.hostname:
            raise SkilledAgentsProxyError("Invalid SKILLED_AGENTS_BASE_URL", upstream_status=500)

        query = urlencode({k: v for k, v in (params or {}).items() if v is not None and v != ""}, doseq=True)
        base_path = parsed.path.rstrip("/")
        target_path = f"{base_path}{path}" if base_path else path
        if query:
            target_path = f"{target_path}?{query}"

        body_bytes = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        headers = {"Accept": "application/json"}
        if body_bytes is not None:
            headers["Content-Type"] = "application/json"
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        conn: HTTPConnection | HTTPSConnection
        if parsed.scheme == "https":
            conn = HTTPSConnection(parsed.hostname, port=parsed.port or 443, timeout=self._connect_timeout)
        else:
            conn = HTTPConnection(parsed.hostname, port=parsed.port or 80, timeout=self._connect_timeout)

        try:
            conn.request(method.upper(), target_path, body=body_bytes, headers=headers)
            if conn.sock is not None:
                conn.sock.settimeout(self._read_timeout)
            response = conn.getresponse()
            payload_raw = response.read().decode("utf-8", errors="replace")
        except socket.timeout as exc:
            raise SkilledAgentsProxyError("SkilledAgents request timed out", upstream_status=504, upstream_body=str(exc)) from exc
        except OSError as exc:
            raise SkilledAgentsProxyError("SkilledAgents service unreachable", upstream_status=502, upstream_body=str(exc)) from exc
        finally:
            conn.close()

        try:
            payload: Any = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {"raw": payload_raw}
        return response.status, payload

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        loop = asyncio.get_running_loop()
        status_code, payload = await loop.run_in_executor(
            None,
            self._request_sync,
            method,
            path,
            params,
            json_body,
        )
        if status_code >= 400:
            raise SkilledAgentsProxyError(
                message=f"SkilledAgents returned HTTP {status_code}",
                upstream_status=status_code,
                upstream_body=payload,
            )
        return payload


_service: SkilledAgentsProxyService | None = None


def get_skilled_agents_proxy_service() -> SkilledAgentsProxyService:
    global _service
    if _service is None:
        base_url = os.getenv("SKILLED_AGENTS_BASE_URL", DEFAULT_SKILLED_AGENTS_BASE_URL).strip() or DEFAULT_SKILLED_AGENTS_BASE_URL
        api_key = os.getenv("SKILLED_AGENTS_API_KEY", "")
        _service = SkilledAgentsProxyService(base_url=base_url, api_key=api_key)
    return _service
