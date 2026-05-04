from __future__ import annotations
import asyncio
import json
import logging
import time
import httpx
from core.config import settings
from core.http_client import get_shared_async_client, run_async
from llm.router import LLMRouter

_RUN_ID: str | None = None

def set_llm_run_id(run_id: str | None) -> None:
    global _RUN_ID
    _RUN_ID = run_id

class LLMError(RuntimeError):
    pass


def _redis_llm_jobs_url() -> str:
    base = settings.redis_broker_base_url.rstrip("/")
    path = (settings.redis_llm_jobs_path or "/llm/jobs").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _extract_embedding_vector(payload: dict) -> list[float]:
    direct = payload.get("embedding")
    if isinstance(direct, list) and direct and all(isinstance(v, (int, float)) for v in direct):
        return [float(v) for v in direct]
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and embeddings:
        first = embeddings[0]
        if isinstance(first, list) and first and all(isinstance(v, (int, float)) for v in first):
            return [float(v) for v in first]
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        vec = data[0].get("embedding")
        if isinstance(vec, list) and vec and all(isinstance(v, (int, float)) for v in vec):
            return [float(v) for v in vec]
    result = payload.get("result")
    if isinstance(result, dict):
        vec = result.get("embedding")
        if isinstance(vec, list) and vec and all(isinstance(v, (int, float)) for v in vec):
            return [float(v) for v in vec]
    return []


async def _embed_via_redis(client: httpx.AsyncClient, text: str) -> list[float]:
    timeout = settings.llm_timeout_seconds
    submit = {
        "source_repo": "dashburg-newtopic-extraction",
        "tenant_tag": "default",
        "idempotency_key": f"dashburg-embed-{int(time.time() * 1000)}",
        "priority": 100,
        "payload": {
            "model": settings.ollama_embed_model,
            "prompt": text,
            "input": text,
            "task": "embeddings",
            "operation": "embeddings",
            "stream": False,
        },
    }
    r = await client.post(_redis_llm_jobs_url(), json=submit, timeout=timeout)
    r.raise_for_status()
    payload = r.json() if r.content else {}
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"redis embedding submit missing job_id: {payload}")

    deadline = time.time() + max(1.0, settings.redis_broker_timeout_s)
    last_state = "queued"
    while time.time() < deadline:
        s = await client.get(f"{settings.redis_broker_base_url.rstrip('/')}/jobs/{job_id}", timeout=timeout)
        s.raise_for_status()
        status = s.json() if s.content else {}
        state = str(status.get("state") or "").strip().lower()
        if state:
            last_state = state
        if state == "done":
            break
        if state in {"failed", "canceled"}:
            raise RuntimeError(f"redis embedding failed id={job_id} state={state}: {status.get('error_details')}")
        await asyncio.sleep(max(0.2, settings.redis_broker_poll_s))
    else:
        raise RuntimeError(f"redis embedding timeout id={job_id} last_state={last_state}")

    out = await client.get(f"{settings.redis_broker_base_url.rstrip('/')}/jobs/{job_id}/result", timeout=timeout)
    out.raise_for_status()
    result = out.json() if out.content else {}
    body = result.get("result_payload") if isinstance(result, dict) else None
    if not isinstance(body, dict):
        body = result if isinstance(result, dict) else {}
    vec = _extract_embedding_vector(body)
    if not vec:
        raise RuntimeError(f"redis embedding missing vector id={job_id}")
    return vec

def validate_llm_config() -> None:
    provider = settings.llm_provider.lower()
    if provider == "openai" and not settings.openai_api_key:
        raise LLMError("LLM_PROVIDER=openai but OPENAI_API_KEY is missing.")
    if provider == "ollama" and not settings.ollama_base_url:
        raise LLMError("LLM_PROVIDER=ollama but OLLAMA_BASE_URL is missing.")
    if provider not in ("openai", "ollama"):
        raise LLMError(f"Unknown LLM_PROVIDER: {provider}")

def chat_json(system: str, user: str) -> dict:
    router = LLMRouter(run_id=_RUN_ID)
    return run_async(router.chat_json(system, user, model=None))

def embed_texts(texts: list[str]) -> list[list[float]]:
    async def _embed():
        if settings.openai_api_key:
            from core.limits import get_limiter
            url = "https://api.openai.com/v1/embeddings"
            headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
            payload = {"model": settings.openai_embed_model, "input": texts}
            client = await get_shared_async_client()
            async with get_limiter("llm_openai"):
                r = await client.post(url, headers=headers, json=payload, timeout=settings.llm_timeout_seconds)
            r.raise_for_status()
            data = r.json()
            return [d["embedding"] for d in data["data"]]
        # ollama embeddings
        from core.limits import get_limiter
        base = settings.ollama_base_url.rstrip("/")
        url = f"{base}/api/embeddings"
        client = await get_shared_async_client()
        out: list[list[float]] = []
        async with get_limiter("llm_local"):
            for t in texts:
                if settings.redis_broker_enabled:
                    try:
                        out.append(await _embed_via_redis(client, t))
                        continue
                    except Exception as exc:
                        logging.getLogger(__name__).warning("redis_embed_failed fallback=ollama error=%s", exc)
                r = await client.post(url, json={"model": settings.ollama_embed_model, "prompt": t}, timeout=settings.llm_timeout_seconds)
                r.raise_for_status()
                data = r.json()
                out.append(data.get("embedding") or [])
        return out

    return run_async(_embed())
