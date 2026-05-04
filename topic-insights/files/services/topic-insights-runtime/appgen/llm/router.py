from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from appgen.config import load_config
from appgen.llm.base import estimate_cost
from appgen.llm.providers import LocalStubProvider, LocalOllamaProvider, StrongOpenAIProvider
from appgen.repo import get_idea, update_run
from appgen.db import get_conn


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _ensure_cache_table() -> None:
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS appgen_llm_cache (cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )


def _daily_usage() -> tuple[int, float]:
    day = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        rows = conn.execute("SELECT metrics_json, started_at FROM appgen_runs").fetchall()
    calls = 0
    cost = 0.0
    for r in rows:
        if (r[1] or "")[:10] != day:
            continue
        m = json.loads(r[0] or "{}")
        calls += int(m.get("calls", 0) or 0)
        cost += float(m.get("cost_usd", 0.0) or 0.0)
    return calls, cost


def _idea_usage(idea_id: str) -> tuple[int, float]:
    with get_conn() as conn:
        rows = conn.execute("SELECT metrics_json FROM appgen_runs WHERE idea_id=?", (idea_id,)).fetchall()
    calls = 0
    cost = 0.0
    for r in rows:
        m = json.loads(r[0] or "{}")
        calls += int(m.get("calls", 0) or 0)
        cost += float(m.get("cost_usd", 0.0) or 0.0)
    return calls, cost


def choose_provider(stage: str) -> tuple[str, str]:
    cfg = load_config()["appgen"]["llm"]
    strong_by_stage = {
        "plan_generate": bool(cfg["use_strong_model_for_plan"]),
        "final_review": bool(cfg["use_strong_model_for_final_review"]),
        "validate": bool(cfg["use_strong_model_for_validation"]),
        "meta_analysis": bool(cfg["use_strong_model_for_meta_analysis"]),
    }
    if strong_by_stage.get(stage, False):
        return cfg["strong_provider"], cfg["strong_model"]
    return cfg["default_provider"], cfg["default_model"]


def _provider_instance(name: str):
    if name == "local_stub":
        return LocalStubProvider()
    if name in ("ollama", "local_ollama"):
        return LocalOllamaProvider()
    if name in ("openai", "strong_openai"):
        from core.config import settings as s
        return StrongOpenAIProvider(s.openai_api_key)
    raise RuntimeError(f"Unknown provider: {name}")


def generate_json(
    prompt: str,
    *,
    stage: str,
    run_id: str,
    idea_id: str | None,
    temperature: float,
    max_output_tokens: int,
    json_schema: dict,
) -> dict[str, Any]:
    cfg = load_config()["appgen"]["llm"]
    provider, model = choose_provider(stage)
    calls_day, cost_day = _daily_usage()
    budget_snapshot = {
        "daily_calls_used": calls_day,
        "daily_calls_remaining": max(0, int(cfg["max_calls_per_day"]) - calls_day),
        "daily_cost_used": round(cost_day, 6),
        "daily_cost_remaining": round(max(0.0, float(cfg["daily_cost_budget_usd"]) - cost_day), 6),
    }
    if provider != "local_stub":
        if calls_day >= int(cfg["max_calls_per_day"]):
            provider, model = "local_stub", "local-stub-v1"
        if cost_day >= float(cfg["daily_cost_budget_usd"]):
            provider, model = "local_stub", "local-stub-v1"
        if idea_id:
            c_i, cost_i = _idea_usage(idea_id)
            budget_snapshot["idea_calls_used"] = c_i
            budget_snapshot["idea_calls_remaining"] = max(0, int(cfg["max_calls_per_idea"]) - c_i)
            budget_snapshot["idea_cost_used"] = round(cost_i, 6)
            budget_snapshot["idea_cost_remaining"] = round(max(0.0, float(cfg["per_idea_cost_budget_usd"]) - cost_i), 6)
            if c_i >= int(cfg["max_calls_per_idea"]) or cost_i >= float(cfg["per_idea_cost_budget_usd"]):
                provider, model = "local_stub", "local-stub-v1"

    _ensure_cache_table()
    cache_key = _hash(f"{provider}|{model}|{temperature}|{max_output_tokens}|{prompt}|{json.dumps(json_schema,sort_keys=True)}")
    if cfg.get("cache_enabled", True):
        with get_conn() as conn:
            row = conn.execute("SELECT payload_json, created_at FROM appgen_llm_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row:
            created = datetime.fromisoformat(row[1])
            if created >= datetime.now(timezone.utc) - timedelta(hours=int(cfg.get("cache_ttl_hours", 168))):
                return json.loads(row[0])

    provider_impl = _provider_instance(provider)
    try:
        result = provider_impl.generate_json(
            prompt,
            model=model,
            temperature=temperature,
            max_output_tokens=min(max_output_tokens, int(cfg["max_output_tokens_per_call"])),
            json_schema=json_schema,
        )
    except Exception:
        # Strong providers are optional; fallback keeps MVP functional without external keys.
        provider = "local_stub"
        model = "local-stub-v1"
        provider_impl = _provider_instance(provider)
        result = provider_impl.generate_json(
            prompt,
            model=model,
            temperature=temperature,
            max_output_tokens=min(max_output_tokens, int(cfg["max_output_tokens_per_call"])),
            json_schema=json_schema,
        )
    cost = estimate_cost(result.tokens_in, result.tokens_out, provider, model)
    with get_conn() as conn:
        if cfg.get("cache_enabled", True):
            conn.execute(
                "INSERT OR REPLACE INTO appgen_llm_cache(cache_key,payload_json,created_at) VALUES (?,?,?)",
                (cache_key, json.dumps(result.data), datetime.now(timezone.utc).isoformat()),
            )
    update_run(
        run_id,
        status="running",
        metrics={"calls": 1, "tokens_in": result.tokens_in, "tokens_out": result.tokens_out, "cost_usd": cost},
        provider=provider,
        model=model,
        budget_snapshot=budget_snapshot,
    )

    if idea_id:
        idea = get_idea(idea_id)
        if idea:
            usage = dict(idea.get("model_usage") or {})
            stage_u = usage.get(stage, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "provider": provider, "model": model})
            stage_u["calls"] += 1
            stage_u["tokens_in"] += result.tokens_in
            stage_u["tokens_out"] += result.tokens_out
            stage_u["cost_usd"] = round(float(stage_u.get("cost_usd", 0.0)) + float(cost), 6)
            stage_u["provider"] = provider
            stage_u["model"] = model
            usage[stage] = stage_u
            from appgen.repo import update_idea
            update_idea(idea_id, {"model_usage": usage})

    return result.data
