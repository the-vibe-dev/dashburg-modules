from __future__ import annotations

import logging

import httpx

from core.config import settings
from core.http_client import get_shared_async_client
from llm.providers.redis_broker import broker_chat_async


async def ollama_chat(system: str, user: str, model: str, temperature: float | None = None) -> tuple[str, dict | None]:
    log = logging.getLogger(__name__)
    eff_temp = settings.ollama_temperature if temperature is None else temperature
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if settings.redis_broker_enabled:
        try:
            content, usage = await broker_chat_async(
                model=model,
                messages=messages,
                temperature=eff_temp,
                num_predict=settings.ollama_num_predict,
                source_repo="dashburg-newtopic",
                timeout_seconds=settings.llm_timeout_seconds,
            )
            log.info("ollama_chat ok endpoint=redis chars=%s", len(content))
            return content, usage
        except Exception as exc:
            log.warning("ollama_chat redis_failed fallback=ollama error=%s", exc)

    base = settings.ollama_base_url.rstrip("/")
    chat_url = f"{base}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
            "temperature": eff_temp,
        },
    }

    client = await get_shared_async_client()
    r = await client.post(chat_url, json=payload, timeout=settings.llm_timeout_seconds)

    # Some proxies expose OpenAI-compatible routes only.
    if r.status_code == 404:
        compat_url = f"{base}/v1/chat/completions"
        compat_payload = {
            "model": model,
            "messages": payload["messages"],
            "temperature": payload["options"]["temperature"],
            "max_tokens": settings.ollama_num_predict,
        }
        r = await client.post(compat_url, json=compat_payload, timeout=settings.llm_timeout_seconds)
        r.raise_for_status()
        data = r.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = data.get("usage")
        log.info("ollama_chat ok endpoint=v1 chars=%s", len(content))
        return content, usage

    r.raise_for_status()
    data = r.json()
    content = (data.get("message") or {}).get("content") or ""
    usage = data.get("eval_count")
    log.info("ollama_chat ok endpoint=api chars=%s", len(content))
    return content, None if not usage else {"completion_tokens": int(usage), "prompt_tokens": int(data.get("prompt_eval_count") or 0)}
