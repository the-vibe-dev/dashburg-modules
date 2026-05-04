from __future__ import annotations
from typing import Any
from appgen.repo import add_pain_point, list_pain_points, create_run, update_run
from appgen.sources.oie_source import extract_from_oie
from appgen.sources.json_source import extract_from_json_folder
from appgen.services.bias import base_prompt, with_bias
from appgen.llm.router import generate_json

PAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "pain_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "severity": {"type": "number"},
                    "category": {"type": "string"},
                },
            },
        }
    },
}


def extract_pain_points(source_type: str = "all", limit: int = 200, use_llm: bool = False) -> dict[str, Any]:
    run_id = create_run("pain_extract", status="running")
    from appgen.events import emit
    emit("appgen.run.created", {"run_id": run_id, "run_type": "pain_extract"})
    items: list[dict[str, Any]] = []
    if source_type in ("all", "oie_db"):
        items.extend(extract_from_oie(limit=limit))
    if source_type in ("all", "json_folder"):
        items.extend(extract_from_json_folder(limit=limit))
    items = items[:limit]

    saved = []
    if use_llm and items:
        prompt = base_prompt("pain_extract.txt").format(input_text="\n\n".join(x["text"] for x in items[:50]))
        data = generate_json(with_bias(prompt), stage="pain_extract", run_id=run_id, idea_id=None, temperature=0.1, max_output_tokens=1200, json_schema=PAIN_SCHEMA)
        for p in data.get("pain_points", []):
            pid = add_pain_point("other", "llm:pain_extract", p.get("text", ""), p.get("severity"), p.get("category"))
            saved.append(pid)
    else:
        for it in items:
            pid = add_pain_point(it["source_type"], it["source_ref"], it["text"], None, None)
            saved.append(pid)

    update_run(run_id, status="success", metrics={"pain_points": len(saved)})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "pain_extract"})
    return {"run_id": run_id, "pain_point_ids": saved}


def create_manual_pain_point(text: str, severity: float | None, category: str | None, source_ref: str) -> str:
    return add_pain_point("manual", source_ref, text, severity, category)


def query_pain_points(source_type: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    return list_pain_points(source_type=source_type, q=q)
