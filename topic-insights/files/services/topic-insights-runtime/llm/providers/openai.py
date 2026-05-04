from __future__ import annotations
import logging
from core.config import settings
from core.http_client import get_shared_async_client

async def openai_chat(system: str, user: str, model: str, temperature: float = 0.2) -> tuple[str, dict | None]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    client = await get_shared_async_client()
    r = await client.post(url, headers=headers, json=payload, timeout=settings.llm_timeout_seconds)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage")
    logging.getLogger(__name__).info("openai_chat ok chars=%s", len(content))
    return content, usage
