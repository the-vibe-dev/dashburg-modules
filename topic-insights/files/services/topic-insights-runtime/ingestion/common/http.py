from __future__ import annotations
import httpx
from core.config import settings
from core.http_client import get_shared_async_client, run_async
from core.retry import retry_async
from core.limits import get_limiter

DEFAULT_HEADERS = {
    "User-Agent": settings.reddit_user_agent,
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

async def async_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 20.0, limiter_name: str | None = None) -> httpx.Response:
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    client = await get_shared_async_client()
    async def _call():
        r = await client.get(url, params=params, headers=hdrs, timeout=timeout)
        r.raise_for_status()
        return r
    if limiter_name:
        async with get_limiter(limiter_name):
            resp = await retry_async(_call, max_retries=3, base=settings.web_search_backoff_base, max_wait_total=15.0)
    else:
        resp = await retry_async(_call, max_retries=3, base=settings.web_search_backoff_base, max_wait_total=15.0)
    return resp

def get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 20.0, limiter_name: str | None = None) -> httpx.Response:
    return run_async(async_get(url, params=params, headers=headers, timeout=timeout, limiter_name=limiter_name))
