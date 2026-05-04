from __future__ import annotations
from pathlib import Path
import sqlite3


def _setup_env(tmp_path, monkeypatch):
    import appgen.db as adb
    import appgen.config as acfg

    monkeypatch.setattr(adb, "DB_PATH", tmp_path / "appgen.sqlite3")
    monkeypatch.setattr(acfg, "CONFIG_PATH", tmp_path / "config.json")
    adb.init_db()
    cfg = acfg.load_config()
    cfg["appgen"]["export"]["appcreator_out_dir"] = str(tmp_path / "appcreator_inbox")
    cfg["appgen"]["workflow"]["allow_stub_persistence"] = False
    acfg.save_config(cfg)


def test_dedupe_prevents_duplicate_inserts(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from appgen.services.generator import generate_ideas
    from appgen.repo import list_ideas

    out1 = generate_ideas([], "same seed", 2, {})
    n1 = len(list_ideas())
    out2 = generate_ideas([], "same seed", 2, {})
    n2 = len(list_ideas())
    assert n2 == n1
    assert len(out2["skipped_duplicates"]) >= 1


def test_stub_like_ideas_rejected_by_default(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from appgen.services.generator import _is_stub_like

    row = {
        "title": "Stub Idea abc",
        "one_liner": "A practical local-first app concept.",
        "problem_statement": "Users need faster way to solve recurring issue.",
        "target_user": "busy professionals",
        "primary_pain_point": "too much manual work",
        "category": "productivity",
    }
    flags = _is_stub_like(row)
    assert "stub_like" in flags


def test_scoring_normalizes_0_10(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from appgen.scoring import normalize_scores

    ok, needs = normalize_scores({
        "pain_score": 9,
        "market_score": 8,
        "monetization_score": 7,
        "complexity_score": 3,
        "distribution_score": 6,
        "ai_leverage_score": 8,
    })
    assert not needs
    assert 0 <= ok["overall_score"] <= 10

    bad, needs2 = normalize_scores({
        "pain_score": 90,
        "market_score": 8,
        "monetization_score": 7,
        "complexity_score": 3,
        "distribution_score": 6,
        "ai_leverage_score": 8,
    })
    assert bad is None
    assert needs2


def test_importer_never_keeps_score_over_10(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from appgen.config import load_config, save_config
    from appgen.services.audit import import_recent_oie_ideas
    from appgen.repo import list_ideas

    oie = tmp_path / "oie.db"
    conn = sqlite3.connect(oie)
    conn.execute("CREATE TABLE idea (idea_id TEXT, idea_name TEXT, solution_summary TEXT, core_problem TEXT, monetization_score REAL, complexity_score REAL, competition_score REAL, demand_score REAL, ctr_prediction REAL, would_build_confidence REAL, opportunity_score REAL, created_at TEXT)")
    conn.execute("INSERT INTO idea VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))", (
        "x1", "Imported X", "solution", "problem", 6.0, 4.0, 7.0, 8.0, 6.0, 7.0, 45.0
    ))
    conn.commit()
    conn.close()

    cfg = load_config()
    cfg["appgen"]["pain_sources"]["oie_db_path_candidates"] = [str(oie)]
    save_config(cfg)

    n = import_recent_oie_ideas(limit=10)
    assert n >= 1
    idea = [x for x in list_ideas() if x["title"] == "Imported X"][0]
    assert idea["needs_scoring"] is True
    assert (idea.get("scores") or {}) == {}
    assert float(idea["source_meta"]["raw_scores"]["overall_score"]) > 10


def test_ideas_and_runs_shape(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    from appgen.services.generator import generate_ideas
    from appgen.repo import list_ideas, list_runs

    generate_ideas([], "shape-test", 1, {})
    ideas = list_ideas(sort="overall_score_desc")
    runs = list_runs(limit=10)

    assert ideas and {"id", "title", "scores", "needs_scoring"}.issubset(set(ideas[0].keys()))
    assert runs and {"id", "run_type", "status", "provider_used", "model_used", "budget_snapshot", "input_summary"}.issubset(set(runs[0].keys()))


def test_generator_near_duplicate_heuristic():
    from appgen.services.generator import _near_duplicate

    a = {
        "title": "Smart Invoice Processor for Freelancers",
        "primary_pain_point": "Manual invoice reconciliation across bank CSV exports",
        "archetype": "workflow_tool",
    }
    b = {
        "title": "Smart Invoice Processing Tool for Freelancers",
        "primary_pain_point": "Manual invoice reconciliation across bank CSV exports",
        "archetype": "workflow_tool",
    }
    assert _near_duplicate(a, b) is True
