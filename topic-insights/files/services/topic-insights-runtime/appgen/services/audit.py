from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from appgen.config import load_config
from appgen.repo import insert_idea, list_ideas
from appgen.scoring import normalize_scores
from appgen.services.generator import generate_ideas
from appgen.services.meta import analyze_meta
from appgen.services.scorer import score_batch


def import_recent_oie_ideas(limit: int = 200) -> int:
    cfg = load_config()["appgen"]["pain_sources"]
    candidates = [Path(p) for p in cfg.get("oie_db_path_candidates", [])]
    db = next((p for p in candidates if p.exists()), None)
    if not db:
        return 0
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    inserted = 0
    try:
        rows = conn.execute("SELECT * FROM idea ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        conn.close()
        return 0

    existing = {i["title"] for i in list_ideas()}
    for r in rows:
        title = r["idea_name"]
        if title in existing:
            continue
        raw_scores = {
            "pain_score": r["competition_score"],
            "market_score": r["demand_score"],
            "monetization_score": r["monetization_score"],
            "complexity_score": r["complexity_score"],
            "distribution_score": r["ctr_prediction"],
            "ai_leverage_score": r["would_build_confidence"],
            "overall_score": r["opportunity_score"],
        }
        normalized, needs_scoring = normalize_scores({k: raw_scores.get(k) for k in ("pain_score", "market_score", "monetization_score", "complexity_score", "distribution_score", "ai_leverage_score")})
        if raw_scores.get("overall_score") and float(raw_scores.get("overall_score") or 0) > 10:
            needs_scoring = True
            normalized = None
        payload = {
            "title": title,
            "one_liner": (r["solution_summary"] or "")[:180],
            "problem_statement": r["core_problem"] or "",
            "target_user": "Imported from OIE",
            "primary_pain_point": r["core_problem"] or "",
            "category": None,
            "status": "researched",
            "execution_stage": "idea",
            "scores": normalized or {},
            "tags": ["imported", "oie"],
            "source_meta": {"source": "oie.db", "idea_id": r["idea_id"], "raw_scores": raw_scores},
            "model_usage": {},
            "feedback_meta": {},
            "needs_scoring": bool(needs_scoring),
            "imported_from": "oie.db",
            "imported_source_ref": f"oie:idea:{r['idea_id']}",
        }
        insert_idea(payload)
        inserted += 1
    conn.close()
    return inserted


def run_initial_audit() -> dict:
    imported = import_recent_oie_ideas(limit=300)
    score_res = score_batch(limit=100)
    meta = analyze_meta()
    generated = None
    workflow_cfg = load_config()["appgen"]["workflow"]
    if workflow_cfg.get("auto_followups_for_missed", True) and meta.get("recommended_seeds"):
        seed = "\n".join(meta.get("recommended_seeds", [])[:3])
        followup_count = max(2, min(5, int(workflow_cfg.get("followup_ideas_per_cluster", 2)) * 2))
        generated = generate_ideas([], seed_text=seed, count=followup_count, constraints={"mode": "audit_followup"})
    return {"imported_ideas": imported, "scored_after_import": score_res.get("scored", 0), "meta": meta, "auto_generated_followups": generated}
