from __future__ import annotations
import json
from appgen.llm.router import generate_json
from appgen.repo import add_artifact, create_run, get_idea, update_idea, update_run
from appgen.events import emit
from appgen.services.bias import base_prompt, with_bias

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendedTechStack": {"type": "object"},
        "mvpFeatures": {"type": "array", "items": {"type": "string"}},
        "v1Features": {"type": "array", "items": {"type": "string"}},
        "milestones": {"type": "array", "items": {"type": "string"}},
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
        "next_idea_suggestions": {"type": "array", "items": {"type": "string"}},
    },
}

VALIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "validation_checks": {"type": "array", "items": {"type": "string"}},
        "result": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}


def plan_generate(idea_id: str) -> dict:
    idea = get_idea(idea_id)
    if not idea:
        raise ValueError("Idea not found")
    run_id = create_run("plan_generate", status="running", idea_id=idea_id)
    emit("appgen.run.created", {"run_id": run_id, "run_type": "plan_generate", "idea_id": idea_id})
    prompt = base_prompt("plan_generate.txt").format(idea_json=json.dumps(idea), workflow_bias_block="")
    data = generate_json(with_bias(prompt), stage="plan_generate", run_id=run_id, idea_id=idea_id, temperature=0.1, max_output_tokens=2000, json_schema=PLAN_SCHEMA)
    aid = add_artifact(idea_id, "plan", "json", json.dumps(data))
    update_idea(idea_id, {"execution_stage": "spec_written"})
    update_run(run_id, status="success", metrics={"artifact_id": aid})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "plan_generate", "idea_id": idea_id})
    emit("appgen.artifact.created", {"artifact_id": aid, "idea_id": idea_id, "kind": "plan"})
    return {"run_id": run_id, "idea_id": idea_id, "artifact_id": aid}


def final_review(idea_id: str) -> dict:
    idea = get_idea(idea_id)
    if not idea:
        raise ValueError("Idea not found")
    run_id = create_run("final_review", status="running", idea_id=idea_id)
    emit("appgen.run.created", {"run_id": run_id, "run_type": "final_review", "idea_id": idea_id})
    plan_txt = ""
    from appgen.repo import list_artifacts
    plans = [a for a in list_artifacts(idea_id) if a["kind"] == "plan"]
    if plans:
        plan_txt = plans[0]["content_text"]
    prompt = base_prompt("final_review.txt").format(idea_json=json.dumps(idea), plan_text=plan_txt, workflow_bias_block="")
    data = generate_json(with_bias(prompt), stage="final_review", run_id=run_id, idea_id=idea_id, temperature=0.1, max_output_tokens=1600, json_schema=REVIEW_SCHEMA)
    aid = add_artifact(idea_id, "final_review", "json", json.dumps(data))
    update_run(run_id, status="success", metrics={"artifact_id": aid})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "final_review", "idea_id": idea_id})
    emit("appgen.artifact.created", {"artifact_id": aid, "idea_id": idea_id, "kind": "final_review"})
    return {"run_id": run_id, "idea_id": idea_id, "artifact_id": aid}


def validate_idea(idea_id: str) -> dict:
    idea = get_idea(idea_id)
    if not idea:
        raise ValueError("Idea not found")
    run_id = create_run("validate", status="running", idea_id=idea_id)
    emit("appgen.run.created", {"run_id": run_id, "run_type": "validate", "idea_id": idea_id})
    prompt = "Validate this idea and return strict JSON only.\n" + json.dumps(idea)
    data = generate_json(with_bias(prompt), stage="validate", run_id=run_id, idea_id=idea_id, temperature=0.0, max_output_tokens=1200, json_schema=VALIDATE_SCHEMA)
    aid = add_artifact(idea_id, "validation_report", "json", json.dumps(data))
    update_run(run_id, status="success", metrics={"artifact_id": aid})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "validate", "idea_id": idea_id})
    emit("appgen.artifact.created", {"artifact_id": aid, "idea_id": idea_id, "kind": "validation_report"})
    return {"run_id": run_id, "idea_id": idea_id, "artifact_id": aid}
