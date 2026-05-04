from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_items: int = 500):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.max_items:
            oldest_key = min(self._store.items(), key=lambda kv: kv[1][0])[0]
            self._store.pop(oldest_key, None)
        self._store[key] = (time.time() + self.ttl_seconds, value)


async def with_retries(
    fn: Callable[[], Any],
    retries: int,
    backoff_base_seconds: float,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries - 1:
                break
            await asyncio.sleep(backoff_base_seconds * (2**attempt))
    raise RuntimeError(f"request failed after retries: {last_error}")
