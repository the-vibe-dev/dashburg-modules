from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, Sequence
from urllib.parse import urlencode, urlsplit


DEFAULT_TOPIC_BASE_URL = "http://127.0.0.1:8080"


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class TopicProxyError(Exception):
    def __init__(self, message: str, upstream_status: int | None = None, upstream_body: Any | None = None):
        super().__init__(message)
        self.message = message
        self.upstream_status = upstream_status
        self.upstream_body = upstream_body


class TopicProxyService:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float = 2.0,
        read_timeout: float = 60.0,
        cache_ttl_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = asyncio.Lock()

    def _request_sync(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        prefix_mode: str = "api_v1",
    ) -> tuple[int, Any]:
        parsed = urlsplit(self._base_url)
        if not parsed.scheme or not parsed.hostname:
            raise TopicProxyError("Invalid TOPIC_BASE_URL configuration", upstream_status=500)

        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        base_path = parsed.path.rstrip("/")
        if prefix_mode == "api_topic":
            target_path = f"{base_path}/api/topic{path}"
        elif prefix_mode == "api_v1":
            target_path = f"{base_path}/api/v1{path}"
        else:
            target_path = f"{base_path}{path}"
        if query:
            target_path = f"{target_path}?{query}"

        body_bytes = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        headers = {"Accept": "application/json"}
        if body_bytes is not None:
            headers["Content-Type"] = "application/json"

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
            raise TopicProxyError("Topic service request timed out", upstream_status=504, upstream_body=str(exc)) from exc
        except OSError as exc:
            raise TopicProxyError("Topic service is unreachable", upstream_status=502, upstream_body=str(exc)) from exc
        finally:
            conn.close()

        try:
            payload: Any = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {"raw": payload_raw}
        return response.status, payload

    def _cache_key(self, path: str, params: dict[str, Any] | None) -> str:
        if not params:
            return path
        chunks = [f"{k}={params[k]}" for k in sorted(params.keys()) if params[k] is not None]
        if not chunks:
            return path
        return f"{path}?{'&'.join(chunks)}"

    async def _get_cached(self, key: str) -> Any | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return entry.value

    async def _set_cached(self, key: str, value: Any) -> None:
        async with self._cache_lock:
            self._cache[key] = CacheEntry(value=value, expires_at=time.monotonic() + self._cache_ttl_seconds)

    async def _clear_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_cache: bool = False,
        prefix_order: Sequence[str] | None = None,
    ) -> Any:
        cache_key = self._cache_key(path, params)
        if method.upper() == "GET" and use_cache:
            cached = await self._get_cached(cache_key)
            if cached is not None:
                return cached

        loop = asyncio.get_running_loop()
        resolved_prefix_order = tuple(prefix_order) if prefix_order else ("api_topic", "api_v1", "raw")
        status_code: int | None = None
        payload: Any = None
        for prefix_mode in resolved_prefix_order:
            status_code, payload = await loop.run_in_executor(
                None,
                self._request_sync,
                method,
                path,
                params,
                json_body,
                prefix_mode,
            )
            if status_code < 400:
                break
            if status_code not in {404, 405}:
                break

        if status_code is None:
            raise TopicProxyError("Topic service request failed", upstream_status=502)

        if status_code >= 400:
            raise TopicProxyError(
                message=f"Topic service returned HTTP {status_code}",
                upstream_status=status_code,
                upstream_body=payload,
            )

        if method.upper() == "GET" and use_cache:
            await self._set_cached(cache_key, payload)
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            await self._clear_cache()
        return payload


_service: TopicProxyService | None = None


def get_topic_proxy_service() -> TopicProxyService:
    global _service
    if _service is None:
        base_url = os.getenv("TOPIC_BASE_URL", DEFAULT_TOPIC_BASE_URL)
        _service = TopicProxyService(base_url=base_url)
    return _service
