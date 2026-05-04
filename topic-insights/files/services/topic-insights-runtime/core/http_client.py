from __future__ import annotations

import asyncio
import logging
import threading

import httpx

from core.config import settings

_client: httpx.AsyncClient | None = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_loop_started: threading.Event | None = None
_use_thread_loop: bool = True


def _start_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    started = threading.Event()

    def runner():
        asyncio.set_event_loop(loop)
        started.set()
        loop.run_forever()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    global _thread, _loop_started
    _thread = t
    _loop_started = started
    started.wait(timeout=2.0)
    return loop


async def _create_client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    timeout = httpx.Timeout(settings.web_search_timeout_seconds)
    headers = {"User-Agent": settings.reddit_user_agent}
    return httpx.AsyncClient(timeout=timeout, limits=limits, headers=headers, follow_redirects=True)


def init_async_client() -> None:
    global _client, _loop, _use_thread_loop
    if _client is not None:
        return
    _use_thread_loop = True
    _loop = _start_loop()
    fut = asyncio.run_coroutine_threadsafe(_create_client(), _loop)
    try:
        _client = fut.result(timeout=5.0)
    except Exception as e:
        logging.getLogger(__name__).error("http_client_init_timeout error=%s", e)
        # Fallback: create client in process loop and stop background loop.
        _client = asyncio.run(_create_client())
        _use_thread_loop = False
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_loop.stop)
        _loop = None
    logging.getLogger(__name__).info("http_client_initialized")


def shutdown_async_client() -> None:
    global _client, _loop, _thread, _loop_started, _use_thread_loop
    if _client is None:
        return
    try:
        if _use_thread_loop and _loop is not None and _loop.is_running():
            async def _close():
                await _client.aclose()

            asyncio.run_coroutine_threadsafe(_close(), _loop).result(timeout=5.0)
            _loop.call_soon_threadsafe(_loop.stop)
        else:
            asyncio.run(_client.aclose())
    except Exception as e:
        logging.getLogger(__name__).warning("http_client_shutdown_error error=%s", e)
    finally:
        _client = None
        _loop = None
        _thread = None
        _loop_started = None
        _use_thread_loop = True
        logging.getLogger(__name__).info("http_client_shutdown")


async def get_shared_async_client() -> httpx.AsyncClient:
    if _client is None:
        init_async_client()
    assert _client is not None
    return _client


def run_async(coro):
    if not _use_thread_loop or _loop is None or not _loop.is_running():
        return asyncio.run(coro)
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()
