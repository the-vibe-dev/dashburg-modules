from __future__ import annotations

import uuid
from pathlib import Path

from core.config import settings
from core.http_client import run_async
from idea_generation.ctr import ctr_heuristic
from idea_generation.pricing import simulate_pricing
from idea_generation.prompt_pack import idea_asset_prompts
from llm.router import LLMRouter
from scoring.appstore_scan import scan_appstore
from scoring.demand_proxy import demand_proxy
from storage.models import Idea, PainCluster

IDEA_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "idea_generator.md"


def _pack_examples(examples: list[str], max_examples: int, char_budget: int) -> list[str]:
    ranked = sorted(
        [e.strip() for e in examples if (e or "").strip()],
        key=lambda x: len(x),
        reverse=True,
    )
    out: list[str] = []
    used = 0
    seen = set()
    for ex in ranked:
        key = ex[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        if used + len(ex) > char_budget and out:
            break
        out.append(ex)
        used += len(ex)
        if len(out) >= max_examples:
            break
    return out


def generate_idea(cluster: PainCluster, cluster_examples: list[str]) -> dict:
    system = "You generate buildable micro-SaaS ideas from pain clusters."
    prompt = IDEA_PROMPT.read_text(encoding="utf-8")
    packed = _pack_examples(cluster_examples, settings.llm_max_examples, settings.llm_max_input_chars // 2)
    user = (
        prompt
        + "\n\nCLUSTER_LABEL:\n"
        + cluster.cluster_label
        + "\n\nEXAMPLES:\n- "
        + "\n- ".join(packed)
    )[: settings.llm_max_input_chars]
    router = LLMRouter()
    return run_async(router.chat_json(system, user, model=None, operation="idea_single"))


def generate_ideas_batch(clusters: list[PainCluster], examples_by_cluster: list[list[str]]) -> list[dict]:
    system = "You generate buildable micro-SaaS ideas from pain clusters."
    prompt = IDEA_PROMPT.read_text(encoding="utf-8")
    lines = [
        'Return JSON only: {"items": [{"index": 0, "idea_name": "...", "core_problem": "...", "solution_summary": "...", "mvp_scope": [], "estimated_build_time_days": 14, "complexity_score": 5, "competition_score": 5, "monetization_score": 5}]}'
    ]

    total_budget = max(4000, settings.llm_max_input_chars - len(prompt) - 1200)
    per_cluster_budget = max(800, total_budget // max(1, len(clusters)))

    for i, c in enumerate(clusters):
        packed = _pack_examples(
            examples_by_cluster[i],
            max_examples=max(6, min(settings.llm_max_examples, 20)),
            char_budget=per_cluster_budget,
        )
        lines.append(
            f"INDEX {i}\nCLUSTER_LABEL:\n{c.cluster_label}\nEXAMPLES:\n- " + "\n- ".join(packed)
        )

    user = (prompt + "\n\n" + "\n\n".join(lines))[: settings.llm_max_input_chars]
    router = LLMRouter()
    data = run_async(router.chat_json(system, user, model=None, operation="idea_batch"))
    return data.get("items") or []


def to_idea(
    cluster: PainCluster,
    data: dict,
    cluster_examples: list[str],
    eval_json: dict | None,
    landing_copy: str | None,
    run_id: str | None = None,
) -> Idea:
    idea_name = str(data.get("idea_name", "Untitled")).strip()[:80]
    core_problem = str(data.get("core_problem", "")).strip()[:1200]
    solution_summary = str(data.get("solution_summary", "")).strip()[:2000]

    prompts = idea_asset_prompts(idea_name, core_problem, solution_summary)
    mvp = list(data.get("mvp_scope") or [])[:16]
    mvp += [
        f"PROMPT:logo::{prompts['logo_prompt']}",
        f"PROMPT:landing::{prompts['landing_prompt']}",
        f"PROMPT:build::{prompts['build_prompt']}",
    ]

    demand = demand_proxy(idea_name or core_problem or cluster.cluster_label)
    pricing = simulate_pricing(idea_name, cluster.cluster_label, float(data.get("monetization_score") or 5))
    appscan = scan_appstore(cluster.cluster_label)

    eval_json = eval_json or {}
    landing_copy = landing_copy or ""
    ctr_h = ctr_heuristic(landing_copy)
    ctr_eval = float(eval_json.get("ctr_prediction", 0.0) or 0.0)
    ctr_norm = max(0.0, min(1.0, ctr_h / 0.25))
    ctr_final = 0.6 * ctr_norm + 0.4 * max(0.0, min(1.0, ctr_eval))
    wb = float(eval_json.get("would_build_confidence", 0.0) or 0.0)

    return Idea(
        idea_id=str(uuid.uuid4()),
        run_id=run_id,
        cluster_id=cluster.cluster_id,
        idea_name=idea_name,
        core_problem=core_problem,
        solution_summary=solution_summary,
        mvp_scope=mvp,
        estimated_build_time_days=max(1, min(365, int(data.get("estimated_build_time_days") or 14))),
        complexity_score=float(data.get("complexity_score") or 5),
        competition_score=float(data.get("competition_score") or 5),
        monetization_score=float(data.get("monetization_score") or 5),
        opportunity_score=float(cluster.opportunity_score),
        demand_score=float(demand.demand_score),
        demand_summary=demand.summary,
        pricing_model=pricing,
        ctr_prediction=float(ctr_final),
        would_build_confidence=float(max(0.0, min(1.0, wb))),
        evaluation=eval_json,
        competitor_apps=appscan.apps,
    )
