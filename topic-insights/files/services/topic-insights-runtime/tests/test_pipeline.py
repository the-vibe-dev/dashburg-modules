import uuid
from datetime import datetime

import pytest

from duckduckgo_search.exceptions import RatelimitException

from storage.db import reset_engine, init_db
from storage.models import RawPost, ExtractedPain, PainCluster, Idea
from core.orchestrator import run_end_to_end, RunParams


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    reset_engine(f"sqlite:///{db_path}")
    init_db()
    return db_path


def _make_post(i: int, source: str = "reddit") -> RawPost:
    return RawPost(
        id=f"{source}:{i}",
        source=source,
        url="https://example.com",
        author="test",
        timestamp=datetime.utcnow(),
        text=f"post {i} text about a painful issue {i}",
        engagement_score=1,
        metadata_={},
    )


def test_ddg_ratelimit_does_not_abort_run(monkeypatch, temp_db):
    # Mock reddit posts; web search rate limit exception should not abort pipeline.
    import ingestion.reddit.search as reddit_search_mod
    import ingestion.reddit.comments as reddit_comments_mod
    import ingestion.web.search as web_search_mod

    monkeypatch.setattr(reddit_search_mod, "reddit_search", lambda *args, **kwargs: [_make_post(1, "reddit")])
    monkeypatch.setattr(reddit_comments_mod, "reddit_fetch_comments", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_search_mod, "web_search", lambda *args, **kwargs: (_ for _ in ()).throw(RatelimitException("rate")))

    # Mock downstream stages to keep test offline
    monkeypatch.setattr("extraction.pipeline.extract_pains", lambda posts, topic: [ExtractedPain(
        pain_id=str(uuid.uuid4()),
        raw_post_id=posts[0].id,
        topic=topic,
        pain_summary="pain",
        emotional_intensity=0.5,
        frustration_keywords=[],
        workaround_detected=False,
        workaround_type=None,
        existing_solution_mentions=[],
        urgency_signal=0.0,
        created_at=datetime.utcnow(),
    )])
    monkeypatch.setattr("clustering.pipeline.cluster_pains", lambda pains: [PainCluster(
        cluster_id=str(uuid.uuid4()),
        cluster_label="label",
        pain_count=len(pains),
        avg_intensity=0.5,
        avg_engagement=0.0,
        top_sources=[],
        competition_signal=0.0,
        monetization_signal=0.0,
        simplicity_score=0.0,
        pain_score=0.0,
        competition_penalty=0.0,
        opportunity_score=1.0,
    )])
    monkeypatch.setattr("scoring.pipeline.score_clusters", lambda clusters: clusters)
    monkeypatch.setattr("idea_generation.pipeline.generate_ideas_for_clusters", lambda scored, topic: [Idea(
        idea_id=str(uuid.uuid4()),
        cluster_id=scored[0].cluster_id,
        idea_name="idea",
        core_problem="problem",
        solution_summary="solution",
        mvp_scope=[],
        estimated_build_time_days=7,
        complexity_score=1.0,
        competition_score=1.0,
        monetization_score=1.0,
        opportunity_score=1.0,
        demand_score=0.0,
        demand_summary={},
        pricing_model={},
        ctr_prediction=0.1,
        would_build_confidence=0.5,
        evaluation={},
        competitor_apps=[],
    )])
    monkeypatch.setattr("reports.pipeline.export_reports", lambda *args, **kwargs: {"html": "x", "json": "y"})

    res = run_end_to_end(RunParams(query="test", topic="t", limit=10, enable_youtube=False))
    assert res["raw_posts"] > 0
    assert res["pains"] > 0
    assert res["clusters"] > 0
    assert res["ideas"] > 0


def test_pipeline_produces_pains_clusters_ideas_with_mock_llm(monkeypatch, temp_db):
    # Provide 30 posts to yield >=5 clusters (k=6) and thus 5 ideas
    posts = [_make_post(i, "reddit_comment" if i % 3 == 0 else "reddit") for i in range(30)]

    from ingestion.pipeline import IngestSummary
    monkeypatch.setattr("ingestion.pipeline.ingest_all", lambda *args, **kwargs: (posts, IngestSummary()))

    # Mock LLM router for extraction + idea generation + evaluation
    async def fake_chat_json(self, system: str, user: str, **kwargs):
        if "CONTENT_LIST" in user:
            items = []
            for line in user.splitlines():
                if line.strip().startswith(tuple(str(i) for i in range(10))):
                    try:
                        idx = int(line.split(":", 1)[0].strip())
                        items.append({
                            "index": idx,
                            "pain_summary": "hard to manage tasks",
                            "emotional_intensity": 0.7,
                            "frustration_keywords": ["time", "overwhelmed"],
                            "workaround_detected": True,
                            "workaround_type": "spreadsheets",
                            "existing_solution_mentions": [],
                            "urgency_signal": 0.5,
                        })
                    except Exception:
                        continue
            return {"items": items}
        if "INDEX" in user and "IDEA_JSON" not in user:
            # idea batch
            items = []
            for line in user.splitlines():
                if line.startswith("INDEX"):
                    idx = int(line.split()[1])
                    items.append({
                        "index": idx,
                        "idea_name": "Task Relief",
                        "core_problem": "People struggle to track tasks",
                        "solution_summary": "Simple task system",
                        "mvp_scope": ["input", "reminders", "summary"],
                        "estimated_build_time_days": 10,
                        "complexity_score": 3,
                        "competition_score": 3,
                        "monetization_score": 4,
                    })
            return {"items": items}
        if "IDEA_JSON" in user:
            items = []
            for line in user.splitlines():
                if line.startswith("INDEX"):
                    idx = int(line.split()[1])
                    items.append({
                        "index": idx,
                        "ctr_prediction": 0.12,
                        "would_build_confidence": 0.6,
                        "landing_copy": "Test landing copy",
                    })
            return {"items": items}
        return {"items": []}

    monkeypatch.setattr("llm.router.LLMRouter.chat_json", fake_chat_json)
    monkeypatch.setattr("extraction.llm.embed_texts", lambda texts: [[float(i)] for i in range(len(texts))])
    monkeypatch.setattr("scoring.competition_scan.scan_competition", lambda *args, **kwargs: type("x", (), {
        "competitor_count_norm": 0.0,
        "seo_saturation_norm": 0.0,
        "funding_signal_norm": 0.0,
        "app_store_presence": 0.0,
        "big_saas_presence": 0.0,
    })())
    monkeypatch.setattr("scoring.demand_proxy.demand_proxy", lambda *args, **kwargs: type("y", (), {"demand_score": 0.5, "summary": {}})())
    monkeypatch.setattr("scoring.appstore_scan.scan_appstore", lambda *args, **kwargs: type("z", (), {"apps": []})())

    res = run_end_to_end(RunParams(query="test", topic="auto", limit=30, enable_youtube=False))
    assert res["pains"] > 0
    assert res["clusters"] > 0
    assert res["ideas"] == 5
