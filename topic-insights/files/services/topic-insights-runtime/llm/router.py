from __future__ import annotations
import json
import logging
import time
import uuid
from core.cache import cache_get, cache_set, make_cache_key
from core.config import settings
from core.limits import get_limiter
from core.retry import retry_async
from llm.providers.ollama import ollama_chat
from llm.providers.openai import openai_chat
from storage.models import ApiCallLog
from storage.repository import insert_api_call_log

_RUN_CALLS: dict[str, int] = {}

class LLMRouter:
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id

    def _provider_chain(self) -> list[str]:
        primary = settings.llm_provider
        fallback = settings.llm_fallback_provider
        chain = [primary]
        if fallback and fallback not in chain:
            chain.append(fallback)
        return chain

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        schema_version: str = "v1",
        cache_ttl_seconds: int | None = None,
        operation: str = "chat_json",
    ) -> dict:
        cache_ttl = cache_ttl_seconds or settings.llm_cache_ttl_seconds
        eff_temp = settings.ollama_temperature if temperature is None else temperature
        cache_key = make_cache_key(
            "llm",
            {
                "system": system,
                "user": user,
                "model": model or "",
                "temperature": eff_temp,
                "schema_version": schema_version,
            },
        )
        cached = cache_get(cache_key)
        if cached:
            insert_api_call_log(
                ApiCallLog(
                    call_id=str(uuid.uuid4()),
                    run_id=self.run_id,
                    provider="cache",
                    operation=operation,
                    success=True,
                    cache_hit=True,
                )
            )
            return cached

        log = logging.getLogger(__name__)
        if self.run_id:
            calls = _RUN_CALLS.get(self.run_id, 0)
            if calls >= settings.llm_max_calls_per_run:
                log.warning("llm_budget_exceeded run_id=%s calls=%s cap=%s", self.run_id, calls, settings.llm_max_calls_per_run)
                raise RuntimeError("run_llm_budget_exceeded")
            _RUN_CALLS[self.run_id] = calls + 1
        for provider in self._provider_chain():
            provider = provider.lower()
            limiter = get_limiter("llm_openai" if provider == "openai" else "llm_local")
            async with limiter:
                start = time.time()
                retries = 0

                async def _call():
                    nonlocal retries
                    retries += 1
                    if provider == "openai":
                        return await openai_chat(system, user, model=model or settings.openai_model_primary, temperature=eff_temp)
                    return await ollama_chat(system, user, model=model or settings.ollama_model, temperature=eff_temp)

                try:
                    text, usage = await retry_async(
                        _call,
                        max_retries=2,
                        base=1.5,
                        max_wait_total=max(20.0, settings.llm_timeout_seconds * 2),
                        on_retry=lambda a, e, s: log.warning("llm_retry provider=%s attempt=%s sleep=%.2fs error=%s:%r", provider, a, s, type(e).__name__, e),
                    )
                    try:
                        data = _parse_json(text)
                    except Exception:
                        # one repair attempt
                        repair_system = "You fix invalid JSON to be valid and minimal."
                        repair_user = "Fix and return valid JSON only:\n" + text
                        if provider == "openai":
                            repaired_text, _ = await openai_chat(
                                repair_system,
                                repair_user,
                                model=model or settings.openai_model_primary,
                                temperature=0.0,
                            )
                        else:
                            repaired_text, _ = await ollama_chat(
                                repair_system,
                                repair_user,
                                model=model or settings.ollama_model,
                                temperature=0.0,
                            )
                        data = _parse_json(repaired_text)
                    cache_set(cache_key, data, cache_ttl)
                    tokens_in = usage.get("prompt_tokens") if usage else None
                    tokens_out = usage.get("completion_tokens") if usage else None
                    cost_est = _estimate_cost(model or settings.openai_model_primary, tokens_in, tokens_out) if usage else None
                    insert_api_call_log(
                        ApiCallLog(
                            call_id=str(uuid.uuid4()),
                            run_id=self.run_id,
                            provider=provider,
                            operation=operation,
                            success=True,
                            retries=retries - 1,
                            latency_ms=(time.time() - start) * 1000,
                            cache_hit=False,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            cost_est=cost_est,
                        )
                    )
                    return data
                except Exception as e:
                    insert_api_call_log(
                        ApiCallLog(
                            call_id=str(uuid.uuid4()),
                            run_id=self.run_id,
                            provider=provider,
                            operation=operation,
                            success=False,
                            retries=retries - 1,
                            latency_ms=(time.time() - start) * 1000,
                            cache_hit=False,
                            error_message=f"{type(e).__name__}: {e}",
                        )
                    )
                    log.warning("llm_provider_failed provider=%s error=%s:%r", provider, type(e).__name__, e)
                    continue
        raise RuntimeError("All LLM providers failed")


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        # try to extract JSON
        import re
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError(f"LLM did not return JSON. Got: {text[:300]}")


def _estimate_cost(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    if tokens_in is None or tokens_out is None:
        return None
    # Rough estimates (USD per 1M tokens); adjust as needed
    prices = {
        "gpt-4o-mini": (0.15, 0.60),
    }
    in_cost, out_cost = prices.get(model, (0.0, 0.0))
    return (tokens_in / 1_000_000) * in_cost + (tokens_out / 1_000_000) * out_cost
