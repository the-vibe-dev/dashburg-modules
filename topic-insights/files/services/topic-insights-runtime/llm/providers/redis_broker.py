from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from core.config import settings
from core.http_client import get_shared_async_client


def _broker_base() -> str:
    return settings.redis_broker_base_url.rstrip("/")


def _llm_jobs_path() -> str:
    path = (settings.redis_llm_jobs_path or "/llm/jobs").strip()
    return path if path.startswith("/") else f"/{path}"


def _extract_text(result_payload: dict[str, Any]) -> str:
    message_value = result_payload.get("message")
    if isinstance(message_value, dict):
        content = message_value.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    candidates = [
        result_payload.get("response"),
        result_payload.get("text"),
        result_payload.get("content"),
        result_payload.get("output"),
        (result_payload.get("result") or {}).get("response")
        if isinstance(result_payload.get("result"), dict)
        else None,
        (result_payload.get("result") or {}).get("message", {}).get("content")
        if isinstance((result_payload.get("result") or {}).get("message"), dict)
        else None,
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    choices = result_payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return ""


def _build_llm_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    num_predict: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        },
    }


async def broker_chat_async(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    num_predict: int,
    source_repo: str = "dashburg",
    timeout_seconds: float | None = None,
) -> tuple[str, dict[str, Any] | None]:
    timeout = timeout_seconds or settings.llm_timeout_seconds
    payload = _build_llm_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        num_predict=num_predict,
    )
    submit_body = {
        "source_repo": source_repo,
        "tenant_tag": "default",
        "idempotency_key": f"dashburg-llm-{int(time.time() * 1000)}",
        "priority": 100,
        "payload": payload,
    }
    base = _broker_base()
    client = await get_shared_async_client()

    submit = await client.post(f"{base}{_llm_jobs_path()}", json=submit_body, timeout=timeout)
    submit.raise_for_status()
    submit_data = submit.json() if submit.content else {}
    job_id = str(submit_data.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"Redis submit missing job_id: {submit_data}")

    deadline = time.time() + max(1.0, settings.redis_broker_timeout_s)
    last_state = "queued"
    while time.time() < deadline:
        row = await client.get(f"{base}/jobs/{job_id}", timeout=timeout)
        row.raise_for_status()
        row_data = row.json() if row.content else {}
        state = str(row_data.get("state") or "").strip().lower()
        if state:
            last_state = state
        if state == "done":
            break
        if state in {"failed", "canceled"}:
            raise RuntimeError(f"Redis LLM job failed id={job_id} state={state}: {row_data.get('error_details')}")
        await asyncio.sleep(max(0.2, settings.redis_broker_poll_s))
    else:
        raise RuntimeError(f"Redis LLM timeout id={job_id} state={last_state}")

    result = await client.get(f"{base}/jobs/{job_id}/result", timeout=timeout)
    result.raise_for_status()
    result_data = result.json() if result.content else {}
    result_payload = result_data.get("result_payload") if isinstance(result_data, dict) else None
    if not isinstance(result_payload, dict):
        result_payload = result_data if isinstance(result_data, dict) else {}
    text = _extract_text(result_payload)
    if not text:
        raise RuntimeError(f"Redis LLM result missing text id={job_id}")
    usage = result_payload.get("usage")
    return text, usage if isinstance(usage, dict) else None


def broker_chat_sync(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    num_predict: int,
    source_repo: str = "dashburg",
    timeout_seconds: float | None = None,
) -> tuple[str, dict[str, Any] | None]:
    timeout = timeout_seconds or settings.llm_timeout_seconds
    payload = _build_llm_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        num_predict=num_predict,
    )
    submit_body = {
        "source_repo": source_repo,
        "tenant_tag": "default",
        "idempotency_key": f"dashburg-llm-{int(time.time() * 1000)}",
        "priority": 100,
        "payload": payload,
    }
    base = _broker_base()
    with httpx.Client(timeout=timeout) as client:
        submit = client.post(f"{base}{_llm_jobs_path()}", json=submit_body)
        submit.raise_for_status()
        submit_data = submit.json() if submit.content else {}
        job_id = str(submit_data.get("job_id") or "").strip()
        if not job_id:
            raise RuntimeError(f"Redis submit missing job_id: {submit_data}")

        deadline = time.time() + max(1.0, settings.redis_broker_timeout_s)
        last_state = "queued"
        while time.time() < deadline:
            row = client.get(f"{base}/jobs/{job_id}")
            row.raise_for_status()
            row_data = row.json() if row.content else {}
            state = str(row_data.get("state") or "").strip().lower()
            if state:
                last_state = state
            if state == "done":
                break
            if state in {"failed", "canceled"}:
                raise RuntimeError(f"Redis LLM job failed id={job_id} state={state}: {row_data.get('error_details')}")
            time.sleep(max(0.2, settings.redis_broker_poll_s))
        else:
            raise RuntimeError(f"Redis LLM timeout id={job_id} state={last_state}")

        result = client.get(f"{base}/jobs/{job_id}/result")
        result.raise_for_status()
        result_data = result.json() if result.content else {}
        result_payload = result_data.get("result_payload") if isinstance(result_data, dict) else None
        if not isinstance(result_payload, dict):
            result_payload = result_data if isinstance(result_data, dict) else {}
        text = _extract_text(result_payload)
        if not text:
            raise RuntimeError(f"Redis LLM result missing text id={job_id}")
        usage = result_payload.get("usage")
        return text, usage if isinstance(usage, dict) else None
