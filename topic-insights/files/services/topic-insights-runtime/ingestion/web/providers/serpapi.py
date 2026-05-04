from __future__ import annotations
import logging
from core.config import settings
from core.http_client import get_shared_async_client
from ingestion.web.types import SearchResult, ProviderUnavailable

async def serpapi_search(query: str, limit: int, recency: str | None = None) -> list[SearchResult]:
    log = logging.getLogger(__name__)
    if not settings.serpapi_api_key:
        raise ProviderUnavailable("missing serpapi key")

    params = {
        "engine": "google",
        "q": query,
        "num": min(limit, settings.web_search_max_results),
        "api_key": settings.serpapi_api_key,
    }
    if recency:
        params["tbs"] = recency
    client = await get_shared_async_client()
    r = await client.get("https://serpapi.com/search.json", params=params, timeout=settings.web_search_timeout_seconds)
    r.raise_for_status()
    data = r.json()
    results = data.get("organic_results", []) or []
    out: list[SearchResult] = []
    for i, r in enumerate(results):
        url = r.get("link") or r.get("url") or ""
        if not url:
            continue
        out.append(
            SearchResult(
                title=r.get("title") or "",
                url=url,
                snippet=r.get("snippet") or "",
                provider="serpapi",
                rank=i + 1,
            )
        )
    log.info("serpapi_results count=%s", len(out))
    return out
