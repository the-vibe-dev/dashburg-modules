from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from appgen.config import load_config
from appgen.events import emit
from appgen.repo import add_artifact, create_run, get_idea, list_artifacts, update_idea, update_run


def export_to_appcreator(idea_id: str) -> dict:
    idea = get_idea(idea_id)
    if not idea:
        raise ValueError("Idea not found")
    run_id = create_run("export_to_appcreator", status="running", idea_id=idea_id)
    emit("appgen.run.created", {"run_id": run_id, "run_type": "export_to_appcreator", "idea_id": idea_id})
    cfg = load_config()["appgen"]
    out_dir = Path(cfg["export"]["appcreator_out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = list_artifacts(idea_id)
    def first(kind: str):
        for a in artifacts:
            if a["kind"] == kind:
                try:
                    return json.loads(a["content_text"])
                except Exception:
                    return a["content_text"]
        return None

    payload = {
        "schema_version": 1,
        "source": "appgen",
        "ideaId": idea_id,
        "title": idea["title"],
        "oneLiner": idea["one_liner"],
        "problemStatement": idea["problem_statement"],
        "targetUser": idea["target_user"],
        "primaryPainPoint": idea["primary_pain_point"],
        "scores": idea["scores"],
        "recommendedTechStack": (first("plan") or {}).get("recommendedTechStack", {}),
        "monetization": {"pricingHints": ["subscription", "usage"]},
        "logoIdeas": [idea["title"] + " icon"],
        "mvpFeatures": (first("plan") or {}).get("mvpFeatures", []),
        "v1Features": (first("plan") or {}).get("v1Features", []),
        "artifacts": {
            "flow": first("flow"),
            "plan": first("plan"),
            "finalReview": first("final_review"),
            "validation": first("validation_report"),
        },
        "createdAt": idea["created_at"],
        "exportedAt": datetime.now(timezone.utc).isoformat(),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    path = out_dir / f"appcreator_job_{idea_id}_{ts}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    appref = {"exported": True, "outDir": str(out_dir), "file": str(path), "exportedAt": payload["exportedAt"]}
    update_idea(idea_id, {"appcreator_ref": appref})
    emit("appgen.idea.updated", {"idea_id": idea_id, "field": "appcreator_ref"})
    add_artifact(idea_id, "validation_report", "json", json.dumps({"exported_file": str(path)}))

    update_run(run_id, status="success", metrics={"file": str(path)})
    emit("appgen.run.updated", {"run_id": run_id, "status": "success", "run_type": "export_to_appcreator", "idea_id": idea_id})
    emit("appgen.export.completed", {"run_id": run_id, "idea_id": idea_id, "file": str(path)})
    return {"run_id": run_id, "file": str(path), "schema_version": 1}
