from __future__ import annotations
import json
from appgen.llm.router import generate_json
from appgen.repo import create_run, get_idea, list_ideas, update_idea, update_run
from appgen.scoring import normalize_scores

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "pain_score": {"type": "number"},
        "market_score": {"type": "number"},
        "monetization_score": {"type": "number"},
        "complexity_score": {"type": "number"},
        "distribution_score": {"type": "number"},
        "ai_leverage_score": {"type": "number"},
    },
}


def score_idea(idea_id: str) -> dict:
    idea = get_idea(idea_id)
    if not idea:
        raise ValueError("Idea not found")
    run_id = create_run("score", status="running", idea_id=idea_id)
    prompt = "Score this app idea from 0..10 for each field and return JSON only.\n" + json.dumps({
        "title": idea["title"],
        "problem_statement": idea["problem_statement"],
        "target_user": idea["target_user"],
        "primary_pain_point": idea["primary_pain_point"],
        "category": idea.get("category"),
    })
    raw = generate_json(prompt, stage="validate", run_id=run_id, idea_id=idea_id, temperature=0.0, max_output_tokens=400, json_schema=SCORE_SCHEMA)
    scores, needs = normalize_scores(raw)
    if not scores:
        update_idea(idea_id, {"needs_scoring": True, "scores": {}})
        update_run(run_id, status="failed", error_text="invalid_score_output")
        return {"idea_id": idea_id, "needs_scoring": True}
    update_idea(idea_id, {"scores": scores, "needs_scoring": needs})
    update_run(run_id, status="success", metrics={"scored": True})
    return {"idea_id": idea_id, "scores": scores, "needs_scoring": False}


def score_batch(limit: int = 50) -> dict:
    ideas = [x for x in list_ideas(sort="updated_desc") if x.get("needs_scoring")][:limit]
    out = []
    for i in ideas:
        out.append(score_idea(i["id"]))
    return {"scored": len(out), "items": out}
