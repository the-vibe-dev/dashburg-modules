from __future__ import annotations
import asyncio
import random
import time
import httpx
from typing import Callable, Awaitable

def default_is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429,) or exc.response.status_code >= 500
    return False

async def retry_async(
    fn: Callable[[], Awaitable],
    *,
    is_retryable: Callable[[Exception], bool] = default_is_retryable,
    max_retries: int = 3,
    base: float = 1.0,
    jitter: float = 0.5,
    max_wait_total: float = 20.0,
    on_retry: Callable[[int, Exception, float], None] | None = None,
):
    attempt = 0
    start = time.time()
    while True:
        try:
            return await fn()
        except Exception as e:
            attempt += 1
            if attempt > max_retries or not is_retryable(e):
                raise
            sleep_s = base * (2 ** (attempt - 1)) + random.random() * jitter
            if time.time() - start + sleep_s > max_wait_total:
                raise
            if on_retry:
                on_retry(attempt, e, sleep_s)
            await asyncio.sleep(sleep_s)
