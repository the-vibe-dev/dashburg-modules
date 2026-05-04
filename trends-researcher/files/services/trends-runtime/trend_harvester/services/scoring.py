from __future__ import annotations

from datetime import datetime, timezone
from math import log10


def _safe_int(value: int | str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def score_topic_instance(source: str, metrics: dict, cross_source_count: int = 1) -> tuple[float, list[dict]]:
    score = 0.0
    reasons: list[dict] = []

    if source == "youtube":
        views = _safe_int(metrics.get("view_count"))
        likes = _safe_int(metrics.get("like_count"))
        comments = _safe_int(metrics.get("comment_count"))

        view_score = min(log10(views + 1) * 12, 40)
        like_score = min(log10(likes + 1) * 10, 25)
        velocity_score = min(log10(comments + 1) * 10, 20)

        score += view_score + like_score + velocity_score
        reasons.extend([
            {"feature": "youtube_views", "weight": 0.45, "value": views, "contribution": round(view_score, 2)},
            {"feature": "youtube_likes", "weight": 0.30, "value": likes, "contribution": round(like_score, 2)},
            {"feature": "youtube_comments_velocity", "weight": 0.25, "value": comments, "contribution": round(velocity_score, 2)},
        ])

    elif source == "reddit":
        post_score = _safe_int(metrics.get("score"))
        comments = _safe_int(metrics.get("num_comments"))
        upvote_ratio = float(metrics.get("upvote_ratio") or 0.0)

        post_score_component = min(log10(post_score + 1) * 18, 35)
        comment_component = min(log10(comments + 1) * 12, 25)
        ratio_component = max(min(upvote_ratio * 20, 20), 0)

        score += post_score_component + comment_component + ratio_component
        reasons.extend([
            {"feature": "reddit_score", "weight": 0.45, "value": post_score, "contribution": round(post_score_component, 2)},
            {"feature": "reddit_comments", "weight": 0.35, "value": comments, "contribution": round(comment_component, 2)},
            {"feature": "reddit_upvote_ratio", "weight": 0.20, "value": upvote_ratio, "contribution": round(ratio_component, 2)},
        ])

    elif source in {"trends", "x"}:
        rank = metrics.get("rank")
        if rank is None:
            trend_signal = 18.0
        else:
            rank_i = max(_safe_int(rank), 1)
            # Keep trends useful without dominating social signals.
            trend_signal = max(35.0 - (rank_i * 0.5), 8.0)
        score += trend_signal
        feature = "google_trends_signal" if source == "trends" else "x_trends_signal"
        reasons.append({"feature": feature, "weight": 1.0, "value": rank, "contribution": round(trend_signal, 2)})

    if cross_source_count > 1:
        bonus = min((cross_source_count - 1) * 8.0, 24.0)
        score += bonus
        reasons.append(
            {
                "feature": "cross_source_bonus",
                "weight": 1.0,
                "value": cross_source_count,
                "contribution": round(bonus, 2),
            }
        )

    return round(score, 2), reasons


def blend_channel_relevance(model_score: float, heuristic_score: float, focus_score: float = 0.0) -> tuple[float, list[dict]]:
    model = _safe_float(model_score)
    heuristic = _safe_float(heuristic_score)
    focus = _safe_float(focus_score)
    score = (model * 0.6) + (heuristic * 0.3) + (focus * 0.1)
    reasons = [
        {"feature": "llm_channel_fit", "weight": 0.6, "value": round(model, 4), "contribution": round(model * 0.6, 4)},
        {
            "feature": "heuristic_channel_fit",
            "weight": 0.3,
            "value": round(heuristic, 4),
            "contribution": round(heuristic * 0.3, 4),
        },
    ]
    if focus > 0:
        reasons.append(
            {"feature": "focus_alignment", "weight": 0.1, "value": round(focus, 4), "contribution": round(focus * 0.1, 4)}
        )
    return round(max(0.0, min(1.0, score)), 4), reasons


def score_topic_for_channel(
    *,
    base_score: float,
    channel_relevance: float,
    source_count: int,
    historical_runs: int,
    action_penalty: float,
    focus_relevance: float = 0.0,
    overall_actionability: float = 0.0,
    published_at: datetime | None = None,
) -> tuple[float, list[dict]]:
    freshness = _freshness_score(published_at)
    diversity = min(max(source_count, 1), 4) / 4
    novelty_penalty = min(max(historical_runs, 0) * 0.04, 0.3)
    base_norm = min(max(_safe_float(base_score) / 120.0, 0.0), 1.0)
    relevance = _safe_float(channel_relevance)
    focus = _safe_float(focus_relevance)
    actionability = _safe_float(overall_actionability)
    action_penalty_norm = min(max(_safe_float(action_penalty) / 100.0, 0.0), 1.0)

    score = (
        (base_norm * 0.35)
        + (relevance * 0.35)
        + (freshness * 0.10)
        + (diversity * 0.08)
        + (focus * 0.07)
        + (actionability * 0.05)
        - novelty_penalty
        - action_penalty_norm
    )
    reasons = [
        {"feature": "trend_strength", "weight": 0.35, "value": round(base_norm, 4), "contribution": round(base_norm * 0.35, 4)},
        {"feature": "channel_relevance", "weight": 0.35, "value": round(relevance, 4), "contribution": round(relevance * 0.35, 4)},
        {"feature": "freshness", "weight": 0.10, "value": round(freshness, 4), "contribution": round(freshness * 0.10, 4)},
        {"feature": "source_diversity", "weight": 0.08, "value": round(diversity, 4), "contribution": round(diversity * 0.08, 4)},
        {"feature": "focus_relevance", "weight": 0.07, "value": round(focus, 4), "contribution": round(focus * 0.07, 4)},
        {"feature": "actionability", "weight": 0.05, "value": round(actionability, 4), "contribution": round(actionability * 0.05, 4)},
        {"feature": "repeat_penalty", "weight": -1.0, "value": historical_runs, "contribution": round(-novelty_penalty, 4)},
        {"feature": "action_penalty", "weight": -1.0, "value": round(action_penalty_norm, 4), "contribution": round(-action_penalty_norm, 4)},
    ]
    return round(max(0.0, score) * 100, 2), reasons


def _safe_float(value: int | float | str | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _freshness_score(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max((datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600.0, 0.0)
    if hours <= 12:
        return 1.0
    if hours <= 24:
        return 0.9
    if hours <= 72:
        return 0.75
    if hours <= 168:
        return 0.55
    return 0.35
