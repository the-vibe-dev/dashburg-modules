from __future__ import annotations
import hashlib
import json
import re
from typing import Any
import httpx
from appgen.llm.base import LLMProvider, LLMResult
from core.config import settings as core_settings
from llm.providers.redis_broker import broker_chat_sync


def _schema_stub(schema: dict[str, Any]) -> Any:
    t = schema.get("type")
    if t == "object":
        out = {}
        for k, v in schema.get("properties", {}).items():
            out[k] = _schema_stub(v)
        return out
    if t == "array":
        return [_schema_stub(schema.get("items", {"type": "string"}))]
    if t == "number":
        return 0.0
    if t == "integer":
        return 0
    if t == "boolean":
        return False
    return ""


class LocalStubProvider(LLMProvider):
    name = "local_stub"

    def generate_json(self, prompt: str, *, model: str, temperature: float, max_output_tokens: int, json_schema: dict) -> LLMResult:
        base = _schema_stub(json_schema)
        marker = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]
        if isinstance(base, dict):
            if "ideas" in base:
                m = re.search(r"Generate\\s+(\\d+)", prompt)
                n = max(1, min(8, int(m.group(1)) if m else 5))
                categories = ["health", "finance", "compliance", "creator_tools", "smb_ops", "education", "logistics", "hospitality"]
                users = ["funeral homes", "HVAC technicians", "creators", "clinic admins", "small retailers", "school coordinators", "dispatch teams", "property managers"]
                pains = [
                    "insurance pre-auth delays",
                    "invoice reconciliation errors",
                    "audit evidence collection",
                    "content rights tracking",
                    "work order scheduling conflicts",
                    "attendance follow-up backlog",
                    "route exception handling",
                    "lease renewal tracking",
                ]
                ideas = []
                for i in range(n):
                    cat = categories[i % len(categories)]
                    usr = users[i % len(users)]
                    pain = pains[i % len(pains)]
                    ideas.append({
                        "title": f"{cat.title().replace('_', '')} Assistant {marker[:4]}{i}",
                        "one_liner": f"Helps {usr} reduce {pain}.",
                        "problem_statement": f"{usr} struggle with {pain} and lose time each week.",
                        "target_user": usr,
                        "primary_pain_point": pain,
                        "category": cat,
                        "scores": {
                            "pain_score": 7.0 + (i % 3),
                            "market_score": 6.5 + ((i + 1) % 3),
                            "monetization_score": 6.8 + ((i + 2) % 2),
                            "complexity_score": 4.0 + (i % 4),
                            "distribution_score": 6.2 + (i % 3),
                            "ai_leverage_score": 7.1 + ((i + 1) % 2),
                        },
                        "tags": [cat, "local-first", "workflow"],
                    })
                base["ideas"] = ideas
            if "seed_directives" in base:
                base["seed_directives"] = ["Explore repeated high-friction workflow pain points"]
        return LLMResult(data=base if isinstance(base, dict) else {"result": base}, tokens_in=max(10, len(prompt) // 4), tokens_out=300)


class LocalOllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or core_settings.ollama_base_url).rstrip("/")

    def generate_json(self, prompt: str, *, model: str, temperature: float, max_output_tokens: int, json_schema: dict) -> LLMResult:
        messages = [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": prompt},
        ]
        text = "{}"
        redis_ok = False
        if core_settings.redis_broker_enabled:
            try:
                text, _ = broker_chat_sync(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    num_predict=max_output_tokens,
                    source_repo="dashburg-newtopic-appgen",
                    timeout_seconds=core_settings.llm_timeout_seconds,
                )
                redis_ok = True
            except Exception:
                redis_ok = False
        if not redis_ok:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "temperature": temperature,
            }
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=core_settings.llm_timeout_seconds)
            r.raise_for_status()
            text = (r.json().get("message") or {}).get("content") or "{}"
        try:
            data = json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            data = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        return LLMResult(data=data, tokens_in=max(10, len(prompt) // 4), tokens_out=max(20, len(text) // 4))


class StrongOpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def generate_json(self, prompt: str, *, model: str, temperature: float, max_output_tokens: int, json_schema: dict) -> LLMResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured; set it to use strong_openai provider")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = httpx.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        usage = body.get("usage") or {}
        return LLMResult(data=data, tokens_in=int(usage.get("prompt_tokens", 0)), tokens_out=int(usage.get("completion_tokens", 0)))
