from __future__ import annotations
import json
from collections import Counter, defaultdict
from typing import Any
from appgen.config import load_config
from appgen.events import emit
from appgen.llm.router import generate_json
from appgen.repo import (
    add_artifact,
    create_run,
    enqueue_followup_seed,
    latest_artifact,
    list_ideas,
    list_pain_points,
    list_artifacts,
    list_runs,
    update_run,
)
from appgen.services.bias import base_prompt, with_bias

META_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_seeds": {"type": "array", "items": {"type": "string"}},
        "recommended_prompt_bias_changes": {"type": "array", "items": {"type": "string"}},
        "underexplored_categories": {"type": "array", "items": {"type": "string"}},
        "top_patterns_from_high_score_ideas": {"type": "array", "items": {"type": "string"}},
    },
}


def _cluster_key(text: str) -> str:
    toks = [t.lower() for t in text.split() if len(t) > 3]
    return " ".join(toks[:3])


def analyze_meta() -> dict[str, Any]:
    run_id = create_run("meta_analysis", status="running")
    emit("appgen.run.created", {"run_id": run_id, "run_type": "meta_analysis"})
    cfg = load_config()["appgen"]["workflow"]
    threshold = float(cfg.get("high_score_threshold", 8.2))
    pains = list_pain_points()
    ideas = list_ideas()

    cluster_counts: dict[str, int] = defaultdict(int)
    for p in pains:
        cluster_counts[_cluster_key(p["text"])] += 1

    idea_clusters = set()
    high_ideas = []
    category_counter = Counter()
    for i in ideas:
        k = _cluster_key(i.get("primary_pain_point", ""))
        idea_clusters.add(k)
        if float((i.get("scores") or {}).get("overall_score", 0.0)) >= threshold:
            high_ideas.append(i)
            if i.get("category"):
                category_counter[i["category"]] += 1

    missed_clusters = []
    for k, c in sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True):
        if c >= 2 and k and k not in idea_clusters:
            sample = [p["text"][:120] for p in pains if _cluster_key(p["text"]) == k][:2]
            missed_clusters.append({"cluster": k, "count": c, "examples": sample})

    repeated_no_win = []
    for k, c in cluster_counts.items():
        if c >= 3 and k not in { _cluster_key(i.get("primary_pain_point", "")) for i in high_ideas }:
            repeated_no_win.append(k)

    suggestion_lines = []
    for i in ideas[:50]:
        for a in list_artifacts(i["id"]):
            if a["kind"] == "final_review":
                try:
                    j = json.loads(a["content_text"])
                except Exception:
                    continue
                for s in j.get("next_idea_suggestions", []):
                    suggestion_lines.append(s)

    recent_runs = list_runs(limit=200)
    duplicate_skips = sum(int((r.get("metrics") or {}).get("skipped_duplicates_count", 0) or 0) for r in recent_runs)
    rejected_quality = sum(int((r.get("metrics") or {}).get("rejected_quality_count", 0) or 0) for r in recent_runs)
    imported_needing_scores = len([i for i in ideas if i.get("imported_from") and i.get("needs_scoring")])

    summary = {
        "missed_clusters": missed_clusters[:10],
        "underexplored_categories": [k for k, _ in category_counter.most_common(5)],
        "repeated_pains_without_high_score": repeated_no_win[:10],
        "next_idea_suggestions": suggestion_lines[:20],
        "duplicate_skips": duplicate_skips,
        "rejected_by_quality_gate": rejected_quality,
        "imported_ideas_needing_scoring": imported_needing_scores,
    }

    prompt = base_prompt("meta_analysis.txt").format(summary=json.dumps(summary), workflow_bias_block="")
    data = generate_json(with_bias(prompt), stage="meta_analysis", run_id=run_id, idea_id=None, temperature=0.1, max_output_tokens=1600, json_schema=META_SCHEMA)

    recommended_seeds = list(dict.fromkeys((data.get("recommended_seeds") or []) + [m["cluster"] for m in missed_clusters[:5]] + suggestion_lines[:5]))
    bias_lines = data.get("recommended_prompt_bias_changes") or []
    if missed_clusters:
        bias_lines.append("Prioritize clusters with repeated high-friction pains that currently have no generated ideas.")

    meta_content = {
        "missed_clusters": missed_clusters,
        "underexplored_categories": data.get("underexplored_categories") or [],
        "top_patterns_from_high_score_ideas": data.get("top_patterns_from_high_score_ideas") or [],
        "recommended_seeds": recommended_seeds,
        "recommended_prompt_bias_changes": bias_lines,
    }
    meta_artifact_id = add_artifact(ideas[0]["id"] if ideas else "global", "meta_analysis", "json", json.dumps(meta_content))

    bias_block_text = "\n".join([f"- {x}" for x in bias_lines]) if bias_lines else "- Keep prompts grounded in specific repeated pains."
    workflow_adjustment = {
        "bias_block_text": bias_block_text,
        "boosted_categories": data.get("underexplored_categories") or [],
        "followup_seed_queue": recommended_seeds,
    }
    wa_artifact_id = add_artifact(ideas[0]["id"] if ideas else "global", "workflow_adjustment", "json", json.dumps(workflow_adjustment))

    for s in recommended_seeds[:20]:
        enqueue_followup_seed(s, {"source": "meta_analysis", "run_id": run_id})

    add_artifact(ideas[0]["id"] if ideas else "global", "prompt_bias_snapshot", "text", bias_block_text)

    update_run(run_id, status="success", metrics={"missed_clusters": len(missed_clusters), "recommended_seeds": len(recommended_seeds)})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "meta_analysis"})
    emit("appgen.meta_analysis.completed", {"run_id": run_id, "meta_artifact_id": meta_artifact_id, "workflow_adjustment_artifact_id": wa_artifact_id})
    return {"run_id": run_id, "meta_artifact_id": meta_artifact_id, "workflow_adjustment_artifact_id": wa_artifact_id, "recommended_seeds": recommended_seeds}


def latest_meta() -> dict[str, Any] | None:
    art = latest_artifact("meta_analysis")
    if not art:
        return None
    return {"artifact_id": art["id"], "content": json.loads(art["content_text"]), "created_at": art["created_at"]}
