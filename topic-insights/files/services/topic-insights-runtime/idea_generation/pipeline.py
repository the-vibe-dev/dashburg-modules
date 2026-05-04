from __future__ import annotations

from clustering.pipeline import get_current_cluster_map
from core.config import settings
from idea_generation.evaluator import evaluate_ideas_batch
from idea_generation.generator import generate_ideas_batch, to_idea
from storage.models import Idea, PainCluster
from storage.repository import find_pains_for_cluster_label, insert_ideas


def _examples_for_cluster(cluster: PainCluster, cmap: dict) -> list[str]:
    pains = cmap.get(cluster.cluster_id, [])
    if pains:
        return [p.pain_summary for p in pains if (p.pain_summary or "").strip()]

    # DB-backed fallback for "analyze DB" and post-restart runs where in-memory map is empty.
    db_pains = find_pains_for_cluster_label(cluster.cluster_label, limit=settings.llm_max_examples)
    return [p.pain_summary for p in db_pains if (p.pain_summary or "").strip()]


def generate_ideas_for_clusters(
    scored_clusters: list[PainCluster],
    topic: str,
    max_ideas: int | None = None,
    run_id: str | None = None,
) -> list[Idea]:
    cmap = get_current_cluster_map()
    ideas: list[Idea] = []

    target_ideas = max_ideas if max_ideas is not None else settings.auto_discovery_ideas_per_run
    candidate_count = max(10, target_ideas * 2)
    top = scored_clusters[: max(1, min(candidate_count, len(scored_clusters)))]
    if not top:
        return []

    examples_by_cluster = [_examples_for_cluster(c, cmap) for c in top]

    idea_items = generate_ideas_batch(top, examples_by_cluster)
    idea_by_index = {int(i.get("index", idx)): i for idx, i in enumerate(idea_items)}

    eval_items = evaluate_ideas_batch(
        [idea_by_index.get(i, {}) for i in range(len(top))],
        [c.cluster_label for c in top],
        examples_by_cluster,
    )
    eval_by_index = {int(i.get("index", idx)): i for idx, i in enumerate(eval_items)}

    scored_items = []
    for i, c in enumerate(top):
        data = idea_by_index.get(i, {})
        eval_json = eval_by_index.get(i, {})
        score = float(eval_json.get("ctr_prediction", 0.0) or 0.0) + float(eval_json.get("would_build_confidence", 0.0) or 0.0)
        scored_items.append((score, i, c, data, eval_json))

    scored_items.sort(key=lambda x: x[0], reverse=True)
    for _, i, c, data, eval_json in scored_items[: max(1, target_ideas)]:
        landing_copy = eval_json.get("landing_copy", "")
        ideas.append(to_idea(c, data, examples_by_cluster[i], eval_json, landing_copy, run_id=run_id))

    insert_ideas(ideas)
    return ideas
