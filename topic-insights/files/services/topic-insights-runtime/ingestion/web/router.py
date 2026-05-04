from __future__ import annotations
import logging
from core.cache import cache_get, cache_set, make_cache_key
from core.config import settings
from core.limits import get_limiter
from core.retry import retry_async
from ingestion.web.providers.ddg import ddg_search
from ingestion.web.providers.serpapi import serpapi_search
from ingestion.web.providers.dataforseo import dataforseo_search
from storage.models import ApiCallLog
from storage.repository import insert_api_call_log
import time
import uuid
from ingestion.web.types import SearchResult, ProviderRateLimited, ProviderUnavailable

_RUN_ID: str | None = None

def set_web_run_id(run_id: str | None) -> None:
    global _RUN_ID
    _RUN_ID = run_id

_PROVIDERS = {
    "ddg": ddg_search,
    "serpapi": serpapi_search,
    "dataforseo": dataforseo_search,
    "none": None,
}

def _provider_chain() -> list[str]:
    if settings.web_search_provider.lower() == "auto":
        return [p.strip() for p in settings.web_search_fallbacks.split(",") if p.strip()]
    chain = [settings.web_search_provider]
    chain += [p.strip() for p in settings.web_search_fallbacks.split(",") if p.strip()]
    # dedupe preserve order
    out = []
    for p in chain:
        if p not in out:
            out.append(p)
    return out

async def search(query: str, limit: int, recency: str | None = None) -> list[SearchResult]:
    log = logging.getLogger(__name__)
    if not settings.web_search_enabled:
        log.warning("web_search_disabled")
        return []

    chain = _provider_chain()
    for provider_name in chain:
        provider_name = provider_name.lower()
        if provider_name == "none":
            log.warning("web_search_none_selected")
            return []
        provider = _PROVIDERS.get(provider_name)
        if provider is None:
            continue

        cache_key = make_cache_key(
            "web",
            {
                "provider": provider_name,
                "query": query,
                "limit": limit,
                "recency": recency or "",
            },
        )
        cached = cache_get(cache_key)
        if cached:
            log.info("web_search_cache_hit provider=%s", provider_name)
            insert_api_call_log(
                ApiCallLog(
                    call_id=str(uuid.uuid4()),
                    run_id=_RUN_ID,
                    provider=provider_name,
                    operation="web_search",
                    success=True,
                    cache_hit=True,
                )
            )
            return [SearchResult(**r) for r in cached.get("results", [])]

        limiter = get_limiter("web")
        async with limiter:
            try:
                start = time.time()
                async def _call():
                    return await provider(query=query, limit=limit, recency=recency)
                results = await retry_async(
                    _call,
                    max_retries=settings.web_search_retries,
                    base=settings.web_search_backoff_base,
                    max_wait_total=settings.web_search_max_wait_total,
                    on_retry=lambda a, e, s: log.warning("web_retry provider=%s attempt=%s sleep=%.2fs error=%s:%r", provider_name, a, s, type(e).__name__, e),
                )
                cache_set(
                    cache_key,
                    {"results": [r.__dict__ for r in results]},
                    settings.web_search_cache_ttl_seconds,
                )
                insert_api_call_log(
                    ApiCallLog(
                        call_id=str(uuid.uuid4()),
                        run_id=_RUN_ID,
                        provider=provider_name,
                        operation="web_search",
                        success=True,
                        retries=0,
                        latency_ms=(time.time() - start) * 1000,
                        cache_hit=False,
                    )
                )
                return results
            except ProviderRateLimited:
                insert_api_call_log(
                    ApiCallLog(
                        call_id=str(uuid.uuid4()),
                        run_id=_RUN_ID,
                        provider=provider_name,
                        operation="web_search",
                        success=False,
                        error_message="rate_limited",
                    )
                )
                log.warning("web_provider_ratelimited provider=%s", provider_name)
                continue
            except ProviderUnavailable as e:
                insert_api_call_log(
                    ApiCallLog(
                        call_id=str(uuid.uuid4()),
                        run_id=_RUN_ID,
                        provider=provider_name,
                        operation="web_search",
                        success=False,
                        error_message=str(e),
                    )
                )
                log.warning("web_provider_unavailable provider=%s error=%s", provider_name, e)
                continue
            except Exception as e:
                insert_api_call_log(
                    ApiCallLog(
                        call_id=str(uuid.uuid4()),
                        run_id=_RUN_ID,
                        provider=provider_name,
                        operation="web_search",
                        success=False,
                        error_message=str(e),
                    )
                )
                log.exception("web_provider_failed provider=%s error=%s", provider_name, e)
                continue

    log.warning("web_search_all_providers_failed")
    return []
