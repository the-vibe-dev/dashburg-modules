from __future__ import annotations

import uuid
from datetime import datetime

from core.orchestrator import RunParams, run_end_to_end
from storage.models import ExtractedPain, Idea, PainCluster, RawPost


def _make_post(i: int) -> RawPost:
    return RawPost(
        id=f"reddit:{i}",
        source="reddit",
        url="https://example.com",
        author="t",
        timestamp=datetime.utcnow(),
        text=f"text {i}",
        engagement_score=1,
        metadata_={},
    )


def test_run_continues_when_x_connector_raises(monkeypatch):
    monkeypatch.setattr("ingestion.reddit.search.reddit_search", lambda *args, **kwargs: [_make_post(1)])
    monkeypatch.setattr("ingestion.reddit.comments.reddit_fetch_comments", lambda *args, **kwargs: [])
    monkeypatch.setattr("ingestion.web.search.web_search", lambda *args, **kwargs: [])
    monkeypatch.setattr("ingestion.pipeline.fetch_x_trends", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("x timeout")))

    monkeypatch.setattr(
        "extraction.pipeline.extract_pains",
        lambda posts, topic: [
            ExtractedPain(
                pain_id=str(uuid.uuid4()),
                raw_post_id=posts[0].id,
                topic=topic,
                pain_summary="pain",
                emotional_intensity=0.4,
                frustration_keywords=[],
                workaround_detected=False,
                workaround_type=None,
                existing_solution_mentions=[],
                urgency_signal=0.2,
                created_at=datetime.utcnow(),
            )
        ],
    )
    monkeypatch.setattr(
        "clustering.pipeline.cluster_pains",
        lambda pains: [
            PainCluster(
                cluster_id=str(uuid.uuid4()),
                cluster_label="label",
                pain_count=1,
                avg_intensity=0.4,
                avg_engagement=0.0,
                top_sources=[],
            )
        ],
    )
    monkeypatch.setattr("scoring.pipeline.score_clusters", lambda clusters: clusters)
    monkeypatch.setattr(
        "idea_generation.pipeline.generate_ideas_for_clusters",
        lambda scored, topic: [
            Idea(
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
            )
        ],
    )
    monkeypatch.setattr("reports.pipeline.export_reports", lambda *args, **kwargs: {"html": "x", "json": "y"})

    res = run_end_to_end(RunParams(query="q", topic="t", limit=10, sources={"x_trends": True}))
    assert res["ideas"] > 0
    assert any(w.get("source") == "x" for w in res.get("warnings", []))

