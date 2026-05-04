from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from appgen.db import get_conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _j(v: Any) -> str:
    return json.dumps(v or {}, ensure_ascii=True)


def _jd(v: str | None, default: Any) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def create_run(run_type: str, status: str = "queued", idea_id: str | None = None, provider: str | None = None, model: str | None = None, input_hash: str | None = None) -> str:
    rid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO appgen_runs(id, run_type, status, provider_used, model_used, input_hash, metrics_json, budget_snapshot_json, input_summary_json, idea_id, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, run_type, status, provider, model, input_hash, _j({}), _j({}), _j({}), idea_id, now_iso()),
        )
    return rid


def update_run(run_id: str, *, status: str, metrics: dict[str, Any] | None = None, error_text: str | None = None, provider: str | None = None, model: str | None = None, budget_snapshot: dict[str, Any] | None = None, input_summary: dict[str, Any] | None = None) -> None:
    with get_conn() as conn:
        old = conn.execute("SELECT metrics_json, budget_snapshot_json, input_summary_json FROM appgen_runs WHERE id=?", (run_id,)).fetchone()
        oldm = _jd(old[0], {}) if old else {}
        oldb = _jd(old[1], {}) if old else {}
        oldi = _jd(old[2], {}) if old else {}
        if metrics:
            oldm.update(metrics)
        if budget_snapshot:
            oldb.update(budget_snapshot)
        if input_summary:
            oldi.update(input_summary)
        conn.execute(
            "UPDATE appgen_runs SET status=?, metrics_json=?, budget_snapshot_json=?, input_summary_json=?, error_text=?, provider_used=COALESCE(?,provider_used), model_used=COALESCE(?,model_used), finished_at=? WHERE id=?",
            (status, _j(oldm), _j(oldb), _j(oldi), error_text, provider, model, now_iso(), run_id),
        )


def insert_idea(payload: dict[str, Any]) -> str:
    iid = payload.get("id") or str(uuid.uuid4())
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO appgen_ideas(
            id,title,one_liner,problem_statement,target_user,primary_pain_point,category,status,execution_stage,
            scores_json,tags_json,source_meta_json,project_ref_json,appcreator_ref_json,model_usage_json,feedback_meta_json,novelty_hash,needs_scoring,quality_flags_json,imported_from,imported_source_ref,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                iid,
                payload.get("title", "Untitled"),
                payload.get("one_liner", ""),
                payload.get("problem_statement", ""),
                payload.get("target_user", ""),
                payload.get("primary_pain_point", ""),
                payload.get("category"),
                payload.get("status", "idea"),
                payload.get("execution_stage", "idea"),
                _j(payload.get("scores", {})),
                _j(payload.get("tags", [])),
                _j(payload.get("source_meta", {})),
                _j(payload.get("project_ref", {})) if payload.get("project_ref") is not None else None,
                _j(payload.get("appcreator_ref", {})) if payload.get("appcreator_ref") is not None else None,
                _j(payload.get("model_usage", {})),
                _j(payload.get("feedback_meta", {})),
                payload.get("novelty_hash"),
                1 if payload.get("needs_scoring", False) else 0,
                _j(payload.get("quality_flags", [])),
                payload.get("imported_from"),
                payload.get("imported_source_ref"),
                payload.get("created_at", ts),
                ts,
            ),
        )
    return iid


def update_idea(iid: str, patch: dict[str, Any]) -> None:
    idea = get_idea(iid)
    if not idea:
        return
    merged = dict(idea)
    merged.update(patch)
    insert_idea(merged)


def list_ideas(status: str | None = None, q: str | None = None, sort: str = "updated_desc", needs_scoring: bool | None = None, imported: bool | None = None, category: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM appgen_ideas"
    clauses = []
    args: list[Any] = []
    if status:
        clauses.append("status=?")
        args.append(status)
    if q:
        clauses.append("(title LIKE ? OR one_liner LIKE ? OR problem_statement LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if needs_scoring is not None:
        clauses.append("needs_scoring=?")
        args.append(1 if needs_scoring else 0)
    if imported is not None:
        clauses.append("imported_from IS NOT NULL" if imported else "imported_from IS NULL")
    if category:
        clauses.append("category=?")
        args.append(category)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if sort in ("score", "overall_score_desc"):
        sql += " ORDER BY json_extract(scores_json, '$.overall_score') DESC"
    elif sort == "updated_desc":
        sql += " ORDER BY updated_at DESC"
    else:
        sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [row_to_idea(r) for r in rows]


def get_idea(iid: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appgen_ideas WHERE id=?", (iid,)).fetchone()
    return row_to_idea(row) if row else None


def row_to_idea(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "one_liner": row["one_liner"],
        "problem_statement": row["problem_statement"],
        "target_user": row["target_user"],
        "primary_pain_point": row["primary_pain_point"],
        "category": row["category"],
        "status": row["status"],
        "execution_stage": row["execution_stage"],
        "scores": _jd(row["scores_json"], {}),
        "tags": _jd(row["tags_json"], []),
        "source_meta": _jd(row["source_meta_json"], {}),
        "project_ref": _jd(row["project_ref_json"], {}),
        "appcreator_ref": _jd(row["appcreator_ref_json"], {}),
        "model_usage": _jd(row["model_usage_json"], {}),
        "feedback_meta": _jd(row["feedback_meta_json"], {}),
        "novelty_hash": row["novelty_hash"] if "novelty_hash" in row.keys() else None,
        "needs_scoring": bool(row["needs_scoring"]) if "needs_scoring" in row.keys() else False,
        "quality_flags": _jd(row["quality_flags_json"], []),
        "imported_from": row["imported_from"] if "imported_from" in row.keys() else None,
        "imported_source_ref": row["imported_source_ref"] if "imported_source_ref" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def add_artifact(idea_id: str, kind: str, content_format: str, content: str) -> str:
    aid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO appgen_artifacts(id, idea_id, kind, content_format, content_text, created_at) VALUES(?,?,?,?,?,?)",
            (aid, idea_id, kind, content_format, content, now_iso()),
        )
    return aid


def list_artifacts(idea_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM appgen_artifacts WHERE idea_id=? ORDER BY created_at DESC", (idea_id,)).fetchall()
    return [dict(r) for r in rows]


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appgen_artifacts WHERE id=?", (artifact_id,)).fetchone()
    return dict(row) if row else None


def add_pain_point(source_type: str, source_ref: str, text: str, severity: float | None = None, category: str | None = None) -> str:
    pid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO appgen_pain_points(id, source_type, source_ref, text, severity, category, extracted_at) VALUES(?,?,?,?,?,?,?)",
            (pid, source_type, source_ref, text, severity, category, now_iso()),
        )
    return pid


def list_pain_points(source_type: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM appgen_pain_points"
    clauses = []
    args: list[Any] = []
    if source_type:
        clauses.append("source_type=?")
        args.append(source_type)
    if q:
        clauses.append("text LIKE ?")
        args.append(f"%{q}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY extracted_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [dict(r) for r in rows]


def add_outbox_event(topic: str, payload: dict[str, Any], status: str = "pending") -> str:
    eid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO appgen_outbox_events(id, topic, payload_json, status, attempts, created_at, delivered_at) VALUES(?,?,?,?,?,?,?)",
            (eid, topic, _j(payload), status, 0, now_iso(), None),
        )
    return eid


def list_outbox(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM appgen_outbox_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def update_outbox_status(event_id: str, status: str, delivered: bool = False) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE appgen_outbox_events SET status=?, attempts=attempts+1, delivered_at=? WHERE id=?",
            (status, now_iso() if delivered else None, event_id),
        )


def enqueue_followup_seed(seed_text: str, source_meta: dict[str, Any]) -> str:
    sid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO appgen_followup_seeds(id, seed_text, source_meta_json, consumed, created_at) VALUES(?,?,?,?,?)",
            (sid, seed_text, _j(source_meta), 0, now_iso()),
        )
    return sid


def consume_followup_seeds(limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM appgen_followup_seeds WHERE consumed=0 ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.executemany("UPDATE appgen_followup_seeds SET consumed=1 WHERE id=?", [(i,) for i in ids])
    out = []
    for r in rows:
        out.append({"id": r["id"], "seed_text": r["seed_text"], "source_meta": _jd(r["source_meta_json"], {})})
    return out


def latest_artifact(kind: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appgen_artifacts WHERE kind=? ORDER BY created_at DESC LIMIT 1", (kind,)).fetchone()
    return dict(row) if row else None


def novelty_exists(novelty_hash: str, window_days: int = 180) -> bool:
    with get_conn() as conn:
        rows = conn.execute("SELECT created_at FROM appgen_ideas WHERE novelty_hash=?", (novelty_hash,)).fetchall()
    if not rows:
        return False
    cutoff = datetime.now(timezone.utc).timestamp() - int(window_days) * 86400
    for r in rows:
        try:
            ts = datetime.fromisoformat(r[0]).timestamp()
            if ts >= cutoff:
                return True
        except Exception:
            return True
    return False


def list_runs(status: str | None = None, run_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM appgen_runs"
    clauses = []
    args: list[Any] = []
    if status:
        clauses.append("status=?")
        args.append(status)
    if run_type:
        clauses.append("run_type=?")
        args.append(run_type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [row_to_run(r) for r in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM appgen_runs WHERE id=?", (run_id,)).fetchone()
    return row_to_run(row) if row else None


def row_to_run(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_type": row["run_type"],
        "status": row["status"],
        "provider_used": row["provider_used"],
        "model_used": row["model_used"],
        "input_hash": row["input_hash"],
        "metrics": _jd(row["metrics_json"], {}),
        "budget_snapshot": _jd(row["budget_snapshot_json"], {}),
        "input_summary": _jd(row["input_summary_json"], {}),
        "idea_id": row["idea_id"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_text": row["error_text"],
    }


def run_metrics_summary() -> dict[str, Any]:
    with get_conn() as conn:
        ideas = conn.execute("SELECT COUNT(*) c FROM appgen_ideas").fetchone()[0]
        pains = conn.execute("SELECT COUNT(*) c FROM appgen_pain_points").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) c FROM appgen_runs").fetchone()[0]
        outbox = conn.execute("SELECT COUNT(*) c FROM appgen_outbox_events").fetchone()[0]
        costs = conn.execute("SELECT metrics_json FROM appgen_runs").fetchall()
    total_cost = 0.0
    total_calls = 0
    total_tokens = 0
    for r in costs:
        m = _jd(r[0], {})
        total_cost += float(m.get("cost_usd", 0.0) or 0.0)
        total_calls += int(m.get("calls", 0) or 0)
        total_tokens += int(m.get("tokens_in", 0) or 0) + int(m.get("tokens_out", 0) or 0)
    return {
        "ideas": ideas,
        "pain_points": pains,
        "runs": runs,
        "outbox_events": outbox,
        "total_cost_usd": round(total_cost, 6),
        "total_calls": total_calls,
        "total_tokens": total_tokens,
    }
