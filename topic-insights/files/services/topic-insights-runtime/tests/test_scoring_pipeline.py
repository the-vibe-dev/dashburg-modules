from __future__ import annotations

from datetime import datetime

from scoring.pipeline import score_clusters
from storage.models import ExtractedPain, PainCluster


def _pain(pid: str, text: str, intensity: float, urgency: float, workaround: bool = False) -> ExtractedPain:
    return ExtractedPain(
        pain_id=pid,
        raw_post_id=f"r-{pid}",
        topic="t",
        pain_summary=text,
        emotional_intensity=intensity,
        frustration_keywords=[],
        workaround_detected=workaround,
        workaround_type=None,
        existing_solution_mentions=[],
        urgency_signal=urgency,
        created_at=datetime.utcnow(),
    )


def test_score_clusters_merges_canonical_labels_and_boosts(monkeypatch):
    clusters = [
        PainCluster(
            cluster_id="a",
            cluster_label="Job Application Ghosting!",
            pain_count=4,
            avg_intensity=0.8,
            avg_engagement=0.0,
            top_sources=[],
        ),
        PainCluster(
            cluster_id="b",
            cluster_label="job application ghosting",
            pain_count=3,
            avg_intensity=0.7,
            avg_engagement=0.0,
            top_sources=[],
        ),
        PainCluster(
            cluster_id="c",
            cluster_label="minor inconvenience",
            pain_count=3,
            avg_intensity=0.2,
            avg_engagement=0.0,
            top_sources=[],
        ),
    ]

    cmap = {
        "a": [_pain("1", "no response from recruiters, ats rejects resume", 0.9, 0.9, True)],
        "b": [_pain("2", "job application ghosting and resume mismatch", 0.8, 0.8)],
        "c": [_pain("3", "light annoyance", 0.2, 0.1)],
    }

    monkeypatch.setattr("scoring.pipeline.get_current_cluster_map", lambda: cmap)

    class _Sig:
        competitor_count_norm = 0.1
        seo_saturation_norm = 0.1
        funding_signal_norm = 0.0

    monkeypatch.setattr("scoring.pipeline.scan_competition", lambda _: _Sig())

    cfg = {
        "weights": {
            "pain": {"engagement": 0.25, "intensity": 0.3, "frequency": 0.3, "workaround_bonus": 0.15},
            "competition_penalty": {"competitor_count": 0.4, "seo_saturation": 0.3, "funding_signal": 0.3},
            "final": {"pain": 0.45, "simplicity": 0.25, "monetization": 0.2, "competition_penalty": 0.2},
        },
        "scales": {"opportunity_score_max": 100.0},
        "simplicity_rules": {},
        "competition_scan": {"enabled": True},
        "theme_boosts": [
            {"keywords": ["job application", "ghosting", "resume", "ats"], "boost": 0.12},
        ],
    }
    monkeypatch.setattr("scoring.pipeline.load_scoring_config", lambda: cfg)

    scored = score_clusters(clusters)
    assert len(scored) == 2
    assert scored[0].pain_count == 7
    assert scored[0].opportunity_score > 0
    assert scored[0].opportunity_score >= scored[1].opportunity_score


def test_score_clusters_applies_x_signal_bonus(monkeypatch):
    clusters = [
        PainCluster(
            cluster_id="x1",
            cluster_label="Bitcoin",
            pain_count=2,
            avg_intensity=0.4,
            avg_engagement=0.0,
            top_sources=[],
        )
    ]

    cmap = {
        "x1": [
            _pain("10", "bitcoin chatter", 0.5, 0.4),
            _pain("11", "bitcoin trend spike", 0.5, 0.4),
        ]
    }
    monkeypatch.setattr("scoring.pipeline.get_current_cluster_map", lambda: cmap)
    monkeypatch.setattr("scoring.pipeline.scan_competition", lambda _: type("x", (), {
        "competitor_count_norm": 0.0,
        "seo_saturation_norm": 0.0,
        "funding_signal_norm": 0.0,
    })())
    monkeypatch.setattr(
        "scoring.pipeline.get_raw_posts_by_ids",
        lambda ids: [
            type("r", (), {"source": "x", "metadata_": {"metrics": {"rank": 3, "post_count_text": "24.5K posts"}}})(),
            type("r", (), {"source": "reddit", "metadata_": {}})(),
        ],
    )

    cfg = {
        "weights": {
            "pain": {"engagement": 0.25, "intensity": 0.3, "frequency": 0.3, "workaround_bonus": 0.15},
            "competition_penalty": {"competitor_count": 0.4, "seo_saturation": 0.3, "funding_signal": 0.3},
            "final": {"pain": 0.45, "simplicity": 0.25, "monetization": 0.2, "competition_penalty": 0.2},
        },
        "scales": {"opportunity_score_max": 100.0},
        "simplicity_rules": {},
        "competition_scan": {"enabled": True},
        "theme_boosts": [],
    }
    monkeypatch.setattr("scoring.pipeline.load_scoring_config", lambda: cfg)

    scored = score_clusters(clusters)
    assert len(scored) == 1
    assert "x" in (scored[0].top_sources or [])
    assert scored[0].opportunity_score > 30.0
