from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.parse import urlencode, urlsplit

DEFAULT_TRENDS_BASE_URL = "http://127.0.0.1:8400"


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class TrendsProxyError(Exception):
    def __init__(self, message: str, upstream_status: int | None = None, upstream_body: Any | None = None):
        super().__init__(message)
        self.message = message
        self.upstream_status = upstream_status
        self.upstream_body = upstream_body


class TrendsProxyService:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float = 2.0,
        read_timeout: float = 12.0,
        cache_ttl_seconds: float = 12.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = threading.Lock()

    def _request_sync(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        parsed = urlsplit(self._base_url)
        if not parsed.scheme or not parsed.hostname:
            raise TrendsProxyError("Invalid DASHBURG_TRENDS_API_BASE_URL configuration", upstream_status=500)

        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        base_path = parsed.path.rstrip("/")
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
            raise TrendsProxyError("Trend service request timed out", upstream_status=504, upstream_body=str(exc)) from exc
        except OSError as exc:
            raise TrendsProxyError("Trend service is unreachable", upstream_status=502, upstream_body=str(exc)) from exc
        finally:
            conn.close()

        try:
            payload: Any = json.loads(payload_raw) if payload_raw else {}
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
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return entry.value

    async def _set_cached(self, key: str, value: Any) -> None:
        with self._cache_lock:
            self._cache[key] = CacheEntry(value=value, expires_at=time.monotonic() + self._cache_ttl_seconds)

    async def _clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_cache: bool = False,
    ) -> Any:
        cache_key = self._cache_key(path, params)
        if method.upper() == "GET" and use_cache:
            cached = await self._get_cached(cache_key)
            if cached is not None:
                return cached

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
            raise TrendsProxyError(
                message=f"Trend service returned HTTP {status_code}",
                upstream_status=status_code,
                upstream_body=payload,
            )

        if method.upper() == "GET" and use_cache:
            await self._set_cached(cache_key, payload)
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            await self._clear_cache()
        return payload


_service: TrendsProxyService | None = None


def get_trends_proxy_service() -> TrendsProxyService:
    global _service
    if _service is None:
        base_url = os.getenv("DASHBURG_TRENDS_API_BASE_URL", DEFAULT_TRENDS_BASE_URL)
        _service = TrendsProxyService(base_url=base_url)
    return _service
