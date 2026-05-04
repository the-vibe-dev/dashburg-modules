from __future__ import annotations
import asyncio
import logging
import time
import random
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException
from core.config import settings
from ingestion.web.types import SearchResult, ProviderRateLimited, ProviderUnavailable

_NEXT_ALLOWED_AT = 0.0

async def ddg_search(query: str, limit: int, recency: str | None = None) -> list[SearchResult]:
    global _NEXT_ALLOWED_AT
    log = logging.getLogger(__name__)
    if time.time() < _NEXT_ALLOWED_AT:
        raise ProviderRateLimited("ddg cooldown")

    max_results = min(limit, settings.web_search_max_results)

    def _run():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    for attempt in range(1, settings.web_search_retries + 1):
        try:
            results = await asyncio.to_thread(_run)
            break
        except RatelimitException as e:
            _NEXT_ALLOWED_AT = time.time() + settings.web_search_cooldown_seconds
            sleep_s = settings.web_search_backoff_base * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
            log.warning("ddg_ratelimit attempt=%s sleep=%.2fs", attempt, sleep_s)
            await asyncio.sleep(sleep_s)
            if attempt == settings.web_search_retries:
                raise ProviderRateLimited(str(e)) from e
        except Exception as e:
            raise ProviderUnavailable(str(e)) from e
    else:
        results = []

    out: list[SearchResult] = []
    for i, r in enumerate(results):
        url = r.get("href") or r.get("url") or ""
        if not url:
            continue
        out.append(
            SearchResult(
                title=r.get("title") or "",
                url=url,
                snippet=r.get("body") or r.get("snippet") or "",
                provider="ddg",
                rank=i + 1,
            )
        )
    log.info("ddg_results count=%s", len(out))
    return out
