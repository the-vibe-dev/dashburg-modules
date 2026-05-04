from __future__ import annotations
import logging
import base64
from core.config import settings
from core.http_client import get_shared_async_client
from ingestion.web.types import SearchResult, ProviderUnavailable

async def dataforseo_search(query: str, limit: int, recency: str | None = None) -> list[SearchResult]:
    log = logging.getLogger(__name__)
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise ProviderUnavailable("missing dataforseo credentials")

    auth = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    headers = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()}
    payload = [
        {
            "keyword": query,
            "language_name": "English",
            "location_name": "United States",
            "device": "desktop",
            "os": "windows",
            "depth": min(limit, settings.web_search_max_results),
        }
    ]
    client = await get_shared_async_client()
    r = await client.post(
        "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
        json=payload,
        headers=headers,
        timeout=settings.web_search_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    items = data.get("tasks", [{}])[0].get("result", [{}])[0].get("items", []) or []
    out: list[SearchResult] = []
    for i, it in enumerate(items):
        if it.get("type") != "organic":
            continue
        url = it.get("url") or ""
        if not url:
            continue
        out.append(
            SearchResult(
                title=it.get("title") or "",
                url=url,
                snippet=it.get("description") or "",
                provider="dataforseo",
                rank=i + 1,
            )
        )
    log.info("dataforseo_results count=%s", len(out))
    return out
