from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from trend_harvester.config import Settings

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "and", "or", "the", "to", "of", "in", "on", "for", "with", "at", "by", "from", "is", "are", "was", "were",
    "be", "this", "that", "these", "those", "it", "its", "as", "into", "about", "over", "under", "after", "before",
    "how", "why", "what", "who", "when", "where", "vs", "via", "new", "latest", "today", "now", "story", "stories",
}
TOKEN_EQUIVALENTS = {
    "afrika": "africa",
}

CATEGORY_KEYWORDS = {
    "News & Politics": {"politics", "policy", "election", "government", "war", "diplomacy", "geopolitics", "news"},
    "Entertainment": {"celebrity", "gossip", "movie", "tv", "music", "anime", "fandom", "entertainment"},
    "Sports": {"sports", "football", "soccer", "nba", "nfl", "match", "tournament", "player"},
    "Pets & Animals": {"cat", "cats", "dog", "dogs", "pet", "pets", "animal", "animals", "kitten", "puppy"},
    "Science & Technology": {"science", "tech", "technology", "ai", "robot", "space", "biology", "physics"},
    "Education": {"explainer", "history", "lesson", "education", "tutorial", "facts", "knowledge"},
    "People & Blogs": {"lifestyle", "personal", "vlog", "devotional", "faith", "christian", "bible", "prayer"},
}

DISQUALIFIERS = {
    "faith": {"cat", "cats", "dog", "dogs", "pet", "pets", "celebrity", "gossip", "paparazzi"},
}

FAITH_TERMS = {"bible", "christian", "scripture", "prayer", "jesus", "church", "faith", "gospel", "devotional", "verse"}


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"[a-z0-9']+", (text or "").lower()):
        tok = TOKEN_EQUIVALENTS.get(raw, raw)
        if len(tok) >= 2 and tok not in STOPWORDS:
            out.append(tok)
    return out


def dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def build_channel_rankings(
    *,
    topic_id: str,
    title: str,
    summary: str,
    channels: list[dict],
    model_scores: dict[str, float],
    focus_fit_scores: dict[str, float],
    legacy_relevance: dict[str, float],
    channel_scores: dict[str, float],
    include_debug: bool,
    settings: Settings,
) -> tuple[list[dict], dict[str, float], dict[str, list[dict]], dict[str, dict]]:
    topic_terms = topic_keywords(title=title, summary=summary)
    topic_categories = infer_categories(topic_terms)

    rankings: list[dict] = []
    filtered_channels: dict[str, float] = {}
    filtered_reasons: dict[str, list[dict]] = {}
    debug_map: dict[str, dict] = {}

    for channel in channels:
        channel_name = channel["display_name"]
        deterministic = score_channel_match(
            title=title,
            summary=summary,
            topic_terms=topic_terms,
            topic_categories=topic_categories,
            channel=channel,
            model_score=float(model_scores.get(channel_name, 0.0) or 0.0),
            focus_fit=float(focus_fit_scores.get(channel_name, 0.0) or 0.0),
            legacy_relevance=float(legacy_relevance.get(channel_name, 0.0) or 0.0),
            final_channel_score=float(channel_scores.get(channel_name, 0.0) or 0.0),
            min_overlap=max(1, int(settings.channel_ranking_min_overlap)),
        )
        debug_map[channel_name] = deterministic["debug"]
        logger.debug(
            "channel_ranking_decision topic_id=%s channel=%s gated=%s relevance_pct=%s overlap_terms=%s reason=%s",
            topic_id,
            channel_name,
            deterministic["debug"].get("gated"),
            deterministic["relevance_pct"],
            ",".join(deterministic["debug"].get("overlap_terms", [])),
            deterministic["debug"].get("reason"),
        )
        if deterministic["relevance_pct"] < max(1, int(settings.channel_ranking_min_relevance_pct)):
            continue
        rankings.append(
            {
                "channel": channel_name,
                "channel_slug": channel["channel_slug"],
                "channel_title": channel["channel_title"],
                "relevance_pct": deterministic["relevance_pct"],
                "score": round(float(channel_scores.get(channel_name, 0.0) or 0.0), 2),
                "metadata_source": channel["metadata_source"],
                **({"ranking_debug": deterministic["debug"]} if include_debug else {}),
            }
        )
        filtered_channels[channel_name] = deterministic["relevance_pct"] / 100.0
        filtered_reasons[channel_name] = deterministic["reasons"]

    rankings.sort(key=lambda item: (-item["relevance_pct"], -item["score"], item["channel"]))
    rankings = rankings[:4]
    filtered_channels = {row["channel"]: filtered_channels[row["channel"]] for row in rankings}
    filtered_reasons = {row["channel"]: filtered_reasons[row["channel"]] for row in rankings}
    return rankings, filtered_channels, filtered_reasons, debug_map


def score_channel_match(
    *,
    title: str,
    summary: str,
    topic_terms: set[str],
    topic_categories: set[str],
    channel: dict,
    model_score: float,
    focus_fit: float,
    legacy_relevance: float,
    final_channel_score: float,
    min_overlap: int,
) -> dict:
    channel_terms = channel_keywords(channel)
    overlap_terms = sorted(topic_terms & channel_terms)
    overlap_count = len(overlap_terms)
    anchor_terms = channel_anchor_terms(channel)
    anchor_overlap = sorted(topic_terms & anchor_terms)
    channel_categories = set(channel.get("youtube_categories", []) or [])
    if channel.get("category"):
        channel_categories.add(channel["category"])
    category_overlap = sorted(topic_categories & channel_categories)

    topic_is_faith = bool(topic_terms & FAITH_TERMS)
    channel_is_faith = bool(channel_terms & FAITH_TERMS) or "daily bible passages" in channel.get("display_name", "").lower()
    disqualified = False
    reason = "matched"
    if overlap_count < min_overlap:
        disqualified = True
        reason = "no keyword overlap"
    elif channel_is_faith and not topic_is_faith and topic_terms & DISQUALIFIERS["faith"]:
        disqualified = True
        reason = "faith disqualifier"

    overlap_score = min(overlap_count / max(min(len(topic_terms), len(channel_terms)), 1), 1.0)
    category_score = 1.0 if category_overlap else 0.0
    anchor_score = min(0.35 + (0.1 * max(len(anchor_overlap) - 1, 0)), 0.45) if anchor_overlap else 0.0
    combined = (
        overlap_score * 0.55
        + anchor_score
        + category_score * 0.15
        + max(model_score, focus_fit) * 0.10
        + legacy_relevance * 0.10
        + min(max(final_channel_score / 100.0, 0.0), 1.0) * 0.05
    )
    if disqualified:
        combined = 0.0

    relevance_pct = int(round(max(0.0, min(1.0, combined)) * 100))
    reasons = [
        {"feature": "keyword_overlap", "value": overlap_terms, "contribution": round(overlap_score * 0.55, 4)},
        {"feature": "channel_anchor_overlap", "value": anchor_overlap, "contribution": round(anchor_score, 4)},
        {"feature": "category_alignment", "value": category_overlap, "contribution": round(category_score * 0.15, 4)},
        {"feature": "model_support", "value": round(max(model_score, focus_fit), 4), "contribution": round(max(model_score, focus_fit) * 0.10, 4)},
        {"feature": "legacy_relevance", "value": round(legacy_relevance, 4), "contribution": round(legacy_relevance * 0.10, 4)},
        {"feature": "rank_score_support", "value": round(final_channel_score, 2), "contribution": round(min(max(final_channel_score / 100.0, 0.0), 1.0) * 0.05, 4)},
    ]
    if disqualified:
        reasons.append({"feature": "gating", "value": reason, "contribution": -1.0})

    return {
        "relevance_pct": relevance_pct,
        "reasons": reasons,
        "debug": {
            "gated": disqualified,
            "reason": reason,
            "overlap_terms": overlap_terms,
            "anchor_overlap": anchor_overlap,
            "topic_categories": sorted(topic_categories),
            "channel_categories": sorted(channel_categories),
            "raw_scores": {
                "overlap_score": round(overlap_score, 4),
                "anchor_score": round(anchor_score, 4),
                "category_score": round(category_score, 4),
                "model_score": round(model_score, 4),
                "focus_fit": round(focus_fit, 4),
                "legacy_relevance": round(legacy_relevance, 4),
                "final_channel_score": round(final_channel_score, 2),
            },
        },
    }


def topic_keywords(*, title: str, summary: str) -> set[str]:
    return set(tokenize(" ".join([title or "", summary or ""])))


def channel_keywords(channel: dict) -> set[str]:
    parts = [
        channel.get("channel_title", ""),
        channel.get("channel_description", ""),
        channel.get("profile", ""),
        " ".join(channel.get("aliases", []) or []),
        " ".join(channel.get("focus_tags", []) or []),
        " ".join(channel.get("query_terms", []) or []),
        " ".join(channel.get("youtube_categories", []) or []),
        channel.get("category", ""),
    ]
    return set(tokenize(" ".join(parts)))


def channel_anchor_terms(channel: dict) -> set[str]:
    parts = [
        channel.get("display_name", ""),
        " ".join(channel.get("aliases", []) or []),
        " ".join(channel.get("query_terms", []) or []),
    ]
    return set(tokenize(" ".join(parts)))


def infer_categories(tokens: set[str]) -> set[str]:
    matched: set[str] = set()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if tokens & keywords:
            matched.add(category)
    return matched
