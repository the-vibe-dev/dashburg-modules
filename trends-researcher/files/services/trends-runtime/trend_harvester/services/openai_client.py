from __future__ import annotations

import json
from typing import Any

import httpx

from trend_harvester.config import get_settings
from trend_harvester.services.openai_key_store import get_openai_api_key


class OpenAIClientError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise OpenAIClientError("empty response")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise OpenAIClientError("response is not valid json") from None
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise OpenAIClientError("response json must be an object")
    return data


async def openai_structured_json(*, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 2500) -> dict[str, Any]:
    settings = get_settings()
    api_key = get_openai_api_key()
    if not api_key:
        raise OpenAIClientError("OpenAI API key is not configured")
    base = settings.openai_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    primary_model = str(settings.openai_large_model or "").strip()
    fallback_model = "gpt-4.1-mini"
    model_candidates = [primary_model]
    if fallback_model not in model_candidates:
        model_candidates.append(fallback_model)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = float(settings.openai_timeout_seconds)
    last_error: str | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model_name in model_candidates:
            model_lower = model_name.lower()
            is_gpt5_family = model_lower.startswith("gpt-5")
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            if is_gpt5_family:
                payload["max_completion_tokens"] = max(200, int(max_tokens))
            else:
                payload["temperature"] = max(0.0, min(1.0, float(temperature)))
                payload["max_tokens"] = max(200, int(max_tokens))
                payload["response_format"] = {"type": "json_object"}
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                root = resp.json()
                message = ((root.get("choices") or [{}])[0].get("message") or {})
                content_raw = message.get("content")
                if isinstance(content_raw, list):
                    parts = []
                    for item in content_raw:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    content = "\n".join(parts).strip()
                else:
                    content = str(content_raw or "").strip()
                if not content:
                    last_error = f"model {model_name} returned empty response"
                    continue
                return _extract_json(content)
            except httpx.HTTPStatusError as exc:
                body = (exc.response.text or "").strip().replace("\n", " ")
                detail = body[:400] if body else "<empty body>"
                last_error = f"model {model_name} HTTP {exc.response.status_code} body={detail}"
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = f"model {model_name} error: {exc}"
                continue
    raise OpenAIClientError(f"openai request failed: {last_error or 'unknown error'}")
