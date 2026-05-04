from __future__ import annotations
import hashlib
import json
import re
from typing import Any
from appgen.llm.router import generate_json
from appgen.repo import (
    add_artifact,
    consume_followup_seeds,
    create_run,
    insert_idea,
    list_pain_points,
    novelty_exists,
    update_run,
)
from appgen.scoring import normalize_scores
from appgen.services.bias import base_prompt, current_bias_block, with_bias
from appgen.events import emit
from appgen.config import load_config
from core.knowledge import format_context as format_knowledge_context
from core.knowledge import maybe_add_record as maybe_add_knowledge_record
from core.knowledge import search_context as search_knowledge_context

IDEA_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "one_liner": {"type": "string"},
                    "problem_statement": {"type": "string"},
                    "target_user": {"type": "string"},
                    "primary_pain_point": {"type": "string"},
                    "category": {"type": "string"},
                    "archetype": {"type": "string"},
                    "icp_segment": {"type": "string"},
                    "differentiation": {"type": "string"},
                    "why_now": {"type": "string"},
                    "evidence_snippets": {"type": "array", "items": {"type": "string"}},
                    "scores": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def novelty_hash(row: dict[str, Any]) -> str:
    src = "|".join([
        _norm(row.get("title", "")),
        _norm(row.get("one_liner", "")),
        _norm(row.get("primary_pain_point", "")),
        _norm(row.get("category", "")),
    ])
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _theme(text: str) -> str:
    toks = [t for t in re.findall(r"[a-zA-Z]+", text.lower()) if len(t) > 3]
    return " ".join(toks[:3])


def _title_signature(value: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(t) >= 3]
    if not tokens:
        return ""
    return " ".join(sorted(set(tokens))[:8])


def _near_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ta = _title_signature(str(a.get("title") or ""))
    tb = _title_signature(str(b.get("title") or ""))
    if ta and tb and ta == tb:
        return True
    pa = _norm(str(a.get("primary_pain_point") or ""))[:120]
    pb = _norm(str(b.get("primary_pain_point") or ""))[:120]
    aa = _norm(str(a.get("archetype") or ""))
    ab = _norm(str(b.get("archetype") or ""))
    return bool(pa and pb and pa == pb and aa and ab and aa == ab)


def _is_stub_like(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if _norm(row.get("target_user", "")) in {"busy professionals", "everyone", "users"}:
        flags.append("generic_target_user")
    if _norm(row.get("primary_pain_point", "")) in {"too much manual work", "manual work", "inefficiency"}:
        flags.append("generic_pain")
    if "practical local-first app concept" in _norm(row.get("one_liner", "")):
        flags.append("template_one_liner")
    if "users need faster way" in _norm(row.get("problem_statement", "")):
        flags.append("template_problem")
    if row.get("title", "").lower().startswith("stub idea"):
        flags.append("stub_like")
    return flags


def _build_prompt(seed_text: str, count: int, constraints: dict[str, Any], points: list[str], followup_text: str, diversity_block: str = "") -> str:
    return with_bias(base_prompt("idea_generate.txt").format(
        count=max(1, count),
        constraints=json.dumps(constraints),
        pain_points="\n".join([f"- {p}" for p in points[:80]]),
        seed_text=(seed_text or "") + ("\nFollow-up seeds (must use at least 1):\n" + followup_text if followup_text else ""),
        workflow_bias_block=current_bias_block() or "",
    ) + ("\n\nDIVERSITY REQUIREMENT:\n" + diversity_block if diversity_block else ""))


def _call_generate(run_id: str, prompt: str) -> list[dict[str, Any]]:
    data = generate_json(prompt, stage="idea_generate", run_id=run_id, idea_id=None, temperature=0.2, max_output_tokens=2200, json_schema=IDEA_SCHEMA)
    return list(data.get("ideas") or [])


def generate_ideas(pain_point_ids: list[str], seed_text: str, count: int, constraints: dict[str, Any]) -> dict[str, Any]:
    run_id = create_run("idea_generate", status="running")
    emit("appgen.run.created", {"run_id": run_id, "run_type": "idea_generate"})
    cfg = load_config()["appgen"]
    wf = cfg["workflow"]

    points = []
    if pain_point_ids:
        allp = {x["id"]: x for x in list_pain_points()}
        points = [allp[i]["text"] for i in pain_point_ids if i in allp]
    if not points:
        points = [x["text"] for x in list_pain_points()[:100]]

    knowledge_query = seed_text or (points[0] if points else "")
    prior_knowledge_rows = search_knowledge_context(knowledge_query, domain="trend_research", limit=3) if knowledge_query else []
    prior_knowledge_block = format_knowledge_context(prior_knowledge_rows)

    followups = consume_followup_seeds(int(wf.get("followup_ideas_per_cluster", 2)))
    followup_text = "\n".join([f"- {x['seed_text']}" for x in followups])

    input_summary = {
        "seed_text": seed_text,
        "pain_point_ids": pain_point_ids,
        "followup_seed_ids": [x["id"] for x in followups],
    }
    update_run(run_id, status="running", input_summary=input_summary)

    prompt = _build_prompt(seed_text, count, constraints, points, followup_text)
    if prior_knowledge_block:
        prompt = f"{prompt}\n\nShared knowledge to reuse when relevant:\n{prior_knowledge_block}"
    ideas_raw = _call_generate(run_id, prompt)
    themes = {_theme(x.get("primary_pain_point", "")) for x in ideas_raw if x.get("primary_pain_point")}
    cats = {(_norm(x.get("category", "")) or "uncategorized") for x in ideas_raw}
    min_cat = min(int(wf.get("min_distinct_categories", 3)), max(1, count))
    min_theme = min(int(wf.get("min_distinct_pain_themes", 3)), max(1, count))

    warnings: list[str] = []
    if len(cats) < min_cat and len(themes) < min_theme:
        warnings.append("diversity_low_regenerate_once")
        block = f"Avoid repeating categories={sorted(list(cats))} and themes={sorted(list(themes))}. Produce distinct ideas."
        regen = _call_generate(run_id, _build_prompt(seed_text, count, constraints, points, followup_text, diversity_block=block))
        if regen:
            ideas_raw = regen

    created_ideas: list[dict[str, Any]] = []
    skipped_duplicates: list[dict[str, Any]] = []
    rejected_by_quality_gate: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []

    for i, row in enumerate(ideas_raw[:count]):
        item = {
            "title": row.get("title") or f"Generated Idea {i+1}",
            "one_liner": row.get("one_liner") or "",
            "problem_statement": row.get("problem_statement") or "",
            "target_user": row.get("target_user") or "",
            "primary_pain_point": row.get("primary_pain_point") or "",
            "category": row.get("category") or "uncategorized",
            "status": "idea",
            "execution_stage": "idea",
            "tags": row.get("tags") or [],
            "source_meta": {
                "pain_point_ids": pain_point_ids,
                "run_id": run_id,
                "followup_seed_ids": [x["id"] for x in followups],
            },
            "model_usage": {},
            "feedback_meta": {},
        }
        n_hash = novelty_hash(item)
        item["novelty_hash"] = n_hash

        if novelty_exists(n_hash, int(wf.get("dedupe_window_days", 180))):
            skipped_duplicates.append({"title": item["title"], "novelty_hash": n_hash})
            continue
        if any(_near_duplicate(item, existing) for existing in accepted_rows):
            skipped_duplicates.append({"title": item["title"], "novelty_hash": n_hash, "reason": "near_duplicate_in_batch"})
            continue

        flags = _is_stub_like(item)
        if flags and not bool(wf.get("allow_stub_persistence", False)):
            rejected_by_quality_gate.append({"title": item["title"], "flags": flags})
            continue

        scores, needs_scoring = normalize_scores(row.get("scores"))
        item["scores"] = scores or {}
        item["needs_scoring"] = bool(needs_scoring)
        item["quality_flags"] = flags
        item["feedback_meta"] = {
            "archetype": row.get("archetype") or "",
            "icp_segment": row.get("icp_segment") or "",
            "differentiation": row.get("differentiation") or "",
            "why_now": row.get("why_now") or "",
            "evidence_snippets": list(row.get("evidence_snippets") or [])[:6],
        }
        if row.get("archetype"):
            item["tags"] = list(dict.fromkeys([*item["tags"], f"archetype:{str(row.get('archetype')).strip().lower()}"]))

        iid = insert_idea(item)
        created_ideas.append({"id": iid, "title": item["title"], "needs_scoring": item["needs_scoring"]})
        accepted_rows.append(item)
        emit("appgen.idea.created", {"idea_id": iid, "title": item["title"], "run_id": run_id})

        flow = {
            "schema_version": 1,
            "problem": item["problem_statement"],
            "target_user": item["target_user"],
            "mvp_flow": ["discover", "activate", "retain"],
        }
        aid = add_artifact(iid, "flow", "json", json.dumps(flow))
        emit("appgen.artifact.created", {"artifact_id": aid, "idea_id": iid, "kind": "flow"})

    if not created_ideas and ideas_raw:
        salvage = ideas_raw[0]
        scores, needs_scoring = normalize_scores(salvage.get("scores"))
        salvage_item = {
            "title": salvage.get("title") or "Recovered Idea",
            "one_liner": salvage.get("one_liner") or "",
            "problem_statement": salvage.get("problem_statement") or "",
            "target_user": salvage.get("target_user") or "",
            "primary_pain_point": salvage.get("primary_pain_point") or "",
            "category": salvage.get("category") or "uncategorized",
            "status": "idea",
            "execution_stage": "idea",
            "tags": list(dict.fromkeys(list(salvage.get("tags") or []) + ["quality:salvaged"])),
            "source_meta": {
                "pain_point_ids": pain_point_ids,
                "run_id": run_id,
                "followup_seed_ids": [x["id"] for x in followups],
            },
            "model_usage": {},
            "feedback_meta": {
                "archetype": salvage.get("archetype") or "",
                "icp_segment": salvage.get("icp_segment") or "",
                "differentiation": salvage.get("differentiation") or "",
                "why_now": salvage.get("why_now") or "",
                "evidence_snippets": list(salvage.get("evidence_snippets") or [])[:6],
            },
            "scores": scores or {},
            "needs_scoring": bool(needs_scoring),
            "quality_flags": ["salvaged_from_empty_output"],
        }
        salvage_item["novelty_hash"] = novelty_hash(salvage_item)
        iid = insert_idea(salvage_item)
        created_ideas.append({"id": iid, "title": salvage_item["title"], "needs_scoring": salvage_item["needs_scoring"]})
        warnings.append("quality_gate_salvage_used")

    if created_ideas:
        add_artifact(created_ideas[0]["id"], "prompt_bias_snapshot", "text", current_bias_block() or "")

    run_metrics = {
        "created_count": len(created_ideas),
        "skipped_duplicates_count": len(skipped_duplicates),
        "rejected_quality_count": len(rejected_by_quality_gate),
        "followup_consumed": len(followups),
        "warnings": warnings,
    }
    update_run(run_id, status="success", metrics=run_metrics)
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "idea_generate"})

    confidence = 0.82 if len(created_ideas) >= max(1, min(count, 2)) else 0.55
    usefulness = 0.78 if created_ideas else 0.2
    maybe_add_knowledge_record(
        {
            "record_type": "trend_summary",
            "title": seed_text or f"AppGen idea generation {run_id[:8]}",
            "summary": f"Generated {len(created_ideas)} reusable ideas from {len(points)} pain points.",
            "content": json.dumps(
                {
                    "seed_text": seed_text,
                    "created_ideas": created_ideas,
                    "warnings": warnings,
                    "followup_seed_ids": [x["id"] for x in followups],
                },
                ensure_ascii=True,
            ),
            "tags": ["appgen", "trend_research", "idea_generation", *[str(c.get("title", "")).lower().replace(" ", "_") for c in created_ideas[:2] if c.get("title")]],
            "domain": "trend_research",
            "topic": seed_text or _theme(points[0] if points else "ideas"),
            "source": {"name": "newtopic.appgen.generator", "run_id": run_id},
            "scores": {
                "confidence": confidence,
                "usefulness": usefulness,
                "created_count": len(created_ideas),
            },
            "status": "verified" if created_ideas else "experimental",
            "metadata": {
                "run_id": run_id,
                "pain_point_ids": pain_point_ids,
                "knowledge_context_hits": len(prior_knowledge_rows),
            },
        },
        confidence=confidence,
        usefulness=usefulness,
        reusable=bool(created_ideas and (seed_text or points)),
    )

    return {
        "run": {"id": run_id, "run_type": "idea_generate", "status": "success", "metrics": run_metrics},
        "created_ideas": created_ideas,
        "skipped_duplicates": skipped_duplicates,
        "rejected_by_quality_gate": rejected_by_quality_gate,
        "warnings": warnings,
    }
