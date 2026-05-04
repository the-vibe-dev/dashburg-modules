from __future__ import annotations

from core.http_client import run_async
from ingestion.web import router as web_router
from ingestion.web.types import ProviderRateLimited


def test_ddg_ratelimit_degrades_to_empty_without_raising(monkeypatch):
    async def ddg_fail(*args, **kwargs):
        raise ProviderRateLimited("rate")

    async def serp_unavailable(*args, **kwargs):
        raise RuntimeError("no key")

    async def data_unavailable(*args, **kwargs):
        raise RuntimeError("no creds")

    web_router._PROVIDERS["ddg"] = ddg_fail
    web_router._PROVIDERS["serpapi"] = serp_unavailable
    web_router._PROVIDERS["dataforseo"] = data_unavailable

    from core.config import settings

    object.__setattr__(settings, "web_search_provider", "auto")
    object.__setattr__(settings, "web_search_fallbacks", "ddg,serpapi,dataforseo,none")

    out = run_async(web_router.search("test", 5))
    assert out == []
