from __future__ import annotations
import asyncio
from core.config import settings

_limiters: dict[tuple[str, int], asyncio.Semaphore] = {}

def get_limiter(name: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = (name, id(loop))
    if key in _limiters:
        return _limiters[key]
    limit = 4
    if name == "web":
        limit = settings.web_max_concurrency
    elif name == "reddit":
        limit = settings.reddit_max_concurrency
    elif name == "youtube":
        limit = settings.youtube_max_concurrency
    elif name == "llm_local":
        limit = settings.llm_local_max_concurrency
    elif name == "llm_openai":
        limit = settings.llm_openai_max_concurrency
    _limiters[key] = asyncio.Semaphore(limit)
    return _limiters[key]
