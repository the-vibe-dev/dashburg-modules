from datetime import datetime, timezone

from trend_harvester.services.scoring import blend_channel_relevance, score_topic_for_channel, score_topic_instance


def test_youtube_scoring_has_expected_reasons():
    score, reasons = score_topic_instance(
        "youtube",
        {"view_count": 500000, "like_count": 20000, "comment_count": 3000},
        cross_source_count=2,
    )
    features = {r["feature"] for r in reasons}
    assert score > 0
    assert "youtube_views" in features
    assert "cross_source_bonus" in features


def test_reddit_scoring_uses_ratio():
    score, reasons = score_topic_instance(
        "reddit",
        {"score": 12000, "num_comments": 1500, "upvote_ratio": 0.91},
    )
    assert score > 0
    assert any(r["feature"] == "reddit_upvote_ratio" for r in reasons)


def test_trends_scoring_defaults_when_rank_missing():
    score, reasons = score_topic_instance("trends", {})
    assert score == 18.0
    assert reasons[0]["feature"] == "google_trends_signal"


def test_x_scoring_defaults_when_rank_missing():
    score, reasons = score_topic_instance("x", {})
    assert score == 18.0
    assert reasons[0]["feature"] == "x_trends_signal"


def test_channel_relevance_blend_prefers_model_with_heuristic_support():
    score, reasons = blend_channel_relevance(0.8, 0.4, 0.2)
    assert score > 0.55
    features = {r["feature"] for r in reasons}
    assert "llm_channel_fit" in features
    assert "heuristic_channel_fit" in features


def test_channel_topic_score_rewards_fresh_diverse_topics():
    score, reasons = score_topic_for_channel(
        base_score=84.0,
        channel_relevance=0.82,
        source_count=3,
        historical_runs=0,
        action_penalty=0.0,
        focus_relevance=0.4,
        overall_actionability=0.6,
        published_at=datetime.now(timezone.utc),
    )
    assert score > 60
    features = {r["feature"] for r in reasons}
    assert "trend_strength" in features
    assert "channel_relevance" in features
    assert "freshness" in features
