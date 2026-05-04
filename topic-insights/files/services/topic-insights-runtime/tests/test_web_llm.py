import math
from datetime import datetime

import pytest

from core.config import settings
from ingestion.web import router as web_router
from core.http_client import run_async
from ingestion.web.types import SearchResult, ProviderRateLimited
from extraction.pain_extractor import extract_pains_from_posts
from storage.models import RawPost


def _set_setting(name, value):
    object.__setattr__(settings, name, value)


@pytest.fixture(autouse=True)
def reset_web_settings():
    _set_setting("web_search_enabled", True)
    _set_setting("web_search_provider", "auto")
    _set_setting("web_search_fallbacks", "ddg,serpapi,dataforseo,none")
    _set_setting("serpapi_api_key", "test")
    _set_setting("dataforseo_login", "user")
    _set_setting("dataforseo_password", "pass")


def test_web_fallback_chain(monkeypatch):
    async def ddg_fail(*args, **kwargs):
        raise ProviderRateLimited("rate")

    async def serpapi_ok(*args, **kwargs):
        return [SearchResult(title="t", url="https://x.com", snippet="s", provider="serpapi", rank=1)]

    async def dataforseo_ok(*args, **kwargs):
        return [SearchResult(title="t2", url="https://y.com", snippet="s2", provider="dataforseo", rank=1)]

    web_router._PROVIDERS["ddg"] = ddg_fail
    web_router._PROVIDERS["serpapi"] = serpapi_ok
    web_router._PROVIDERS["dataforseo"] = dataforseo_ok

    results = run_async(web_router.search("q", 5))
    assert results
    assert results[0].provider == "serpapi"


def test_web_cache_hit(monkeypatch):
    calls = {"n": 0}

    async def serpapi_ok(*args, **kwargs):
        calls["n"] += 1
        return [SearchResult(title="t", url="https://x.com", snippet="s", provider="serpapi", rank=1)]

    _set_setting("web_search_provider", "serpapi")
    web_router._PROVIDERS["serpapi"] = serpapi_ok

    q = "unique-query-cache-" + str(datetime.utcnow().timestamp())
    res1 = run_async(web_router.search(q, 5))
    res2 = run_async(web_router.search(q, 5))
    assert calls["n"] == 1
    assert res1 and res2


def test_llm_batching_reduces_calls(monkeypatch):
    calls = {"n": 0}
    _set_setting("llm_batch_size", 5)

    async def fake_chat_json(self, system, user, **kwargs):
        calls["n"] += 1
        # Return one item per indexed line
        items = []
        for line in user.splitlines():
            if line.strip().startswith(tuple(str(i) for i in range(10))):
                idx = int(line.split(":", 1)[0].strip())
                items.append({
                    "index": idx,
                    "pain_summary": "pain",
                    "emotional_intensity": 0.5,
                    "frustration_keywords": [],
                    "workaround_detected": False,
                    "workaround_type": None,
                    "existing_solution_mentions": [],
                    "urgency_signal": 0.0,
                })
        return {"items": items}

    monkeypatch.setattr("llm.router.LLMRouter.chat_json", fake_chat_json)

    posts = [
        RawPost(
            id=f"r:{i}",
            source="reddit",
            url="https://example.com",
            author="a",
            timestamp=datetime.utcnow(),
            text=f"text {i}",
            engagement_score=0,
            metadata_={},
        )
        for i in range(12)
    ]
    pains = extract_pains_from_posts(posts, topic="t")
    assert len(pains) > 0
    assert calls["n"] == math.ceil(len(posts) / settings.llm_batch_size)
