from __future__ import annotations

from collections import defaultdict
import re
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from trend_harvester.models import Analysis, Topic, TopicInstance


def export_topic_factory_v1(db: Session, topic_ids: list[str]) -> dict:
    topics = db.scalars(select(Topic).where(Topic.id.in_(topic_ids))).all()
    topics_by_id = {topic.id: topic for topic in topics}
    result = []
    for topic_id in topic_ids:
        topic = topics_by_id.get(topic_id)
        if not topic:
            continue
        analysis = db.scalar(
            select(Analysis)
            .where(Analysis.topic_id == topic.id)
            .order_by(desc(Analysis.created_at))
            .limit(1)
        )
        source_count = db.scalar(
            select(func.count(func.distinct(TopicInstance.source))).where(TopicInstance.topic_id == topic.id)
        )
        result.append(
            {
                "topic_id": topic.id,
                "title": topic.canonical_title,
                "summary": analysis.llm_summary if analysis else "",
                "research_angles": analysis.angle_suggestions_json if analysis else [],
                "source_count": source_count or 0,
            }
        )
    return {"topics": result}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _dominant_source(source_scores: dict[str, float]) -> str:
    if not source_scores:
        return "mixed"
    return max(source_scores, key=source_scores.get)


def _audience_for_source(source: str) -> str:
    if source == "youtube":
        return "viewers actively searching for explainers and demos"
    if source == "reddit":
        return "problem-aware communities discussing implementation pain"
    if source == "trends":
        return "broad interest users with rising discovery intent"
    return "early adopters looking for practical solutions"


def _distribution_for_type(idea_type: str, source: str) -> str:
    if idea_type == "video":
        return "YouTube channel + Shorts clips + weekly newsletter recap"
    if idea_type == "app":
        return "SEO landing page + subreddit launch threads + creator partnerships"
    if idea_type == "saas":
        return "LinkedIn outbound + direct founder outreach + integrations marketplace"
    return _audience_for_source(source)


def _build_scope_for_type(idea_type: str) -> str:
    if idea_type == "video":
        return "small"
    if idea_type == "app":
        return "medium"
    return "large"


def _ttv_for_type(idea_type: str) -> int:
    if idea_type == "video":
        return 3
    if idea_type == "app":
        return 14
    return 30


def _extract_theme(title: str) -> str:
    parts = re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", title.lower())
    stop = {"with", "from", "that", "this", "your", "about", "into", "over", "under", "after", "before", "using"}
    for token in parts:
        if token in stop:
            continue
        return token
    return "general"


def export_idea_factory_v2(db: Session, topic_ids: list[str], run_id: str | None = None) -> dict:
    topics = db.scalars(select(Topic).where(Topic.id.in_(topic_ids))).all()
    topics_by_id = {topic.id: topic for topic in topics}
    analysis_rows = db.scalars(
        select(Analysis).where(Analysis.topic_id.in_(topic_ids)).order_by(desc(Analysis.created_at))
    ).all()
    analysis_by_topic: dict[str, Analysis] = {}
    for row in analysis_rows:
        if row.topic_id not in analysis_by_topic:
            analysis_by_topic[row.topic_id] = row

    instance_query = select(
        TopicInstance.topic_id,
        TopicInstance.source,
        TopicInstance.url,
        TopicInstance.score,
    ).where(TopicInstance.topic_id.in_(topic_ids))
    if run_id:
        instance_query = instance_query.where(TopicInstance.run_id == run_id)
    instance_rows = db.execute(instance_query).all()

    source_scores_by_topic: dict[str, dict[str, float]] = defaultdict(dict)
    evidence_links: dict[str, list[dict]] = defaultdict(list)
    for row in instance_rows:
        source_scores_by_topic[row.topic_id][row.source] = source_scores_by_topic[row.topic_id].get(row.source, 0.0) + float(row.score or 0.0)
        if len(evidence_links[row.topic_id]) < 5:
            evidence_links[row.topic_id].append(
                {
                    "source": row.source,
                    "url": row.url,
                    "signal": f"score={round(float(row.score or 0.0), 2)}",
                }
            )

    topics_payload: list[dict] = []
    ideas: list[dict] = []
    score_breakdowns: dict[str, dict] = {}
    for topic_id in topic_ids:
        topic = topics_by_id.get(topic_id)
        if not topic:
            continue
        analysis = analysis_by_topic.get(topic_id)
        source_scores = source_scores_by_topic.get(topic_id, {})
        dominant_source = _dominant_source(source_scores)
        source_count = len(source_scores) or 1
        total_score = sum(source_scores.values())
        trend_strength = _clamp01(min(1.0, total_score / 40.0))
        evidence_strength = _clamp01((len(evidence_links.get(topic_id, [])) / 5.0 + source_count / 3.0) / 2.0)
        audience_clarity = _clamp01(0.75 if dominant_source in {"youtube", "reddit"} else 0.62)
        distribution_fit = _clamp01(0.8 if dominant_source == "youtube" else 0.72 if dominant_source == "reddit" else 0.68)
        novelty = _clamp01(0.45 + source_count * 0.15)
        base_summary = (analysis.llm_summary if analysis else "").strip()
        hooks = analysis.angle_suggestions_json if analysis else []

        topics_payload.append(
            {
                "topic_id": topic_id,
                "title": topic.canonical_title,
                "summary": base_summary,
                "research_angles": hooks,
                "source_count": source_count,
            }
        )

        for idea_type in ("video", "app", "saas"):
            idea_id = str(uuid4())
            build_feasibility = 0.86 if idea_type == "video" else 0.66 if idea_type == "app" else 0.48
            monetization = 0.52 if idea_type == "video" else 0.72 if idea_type == "app" else 0.84
            execution_risk = _clamp01(1.0 - build_feasibility * 0.8)
            confidence = _clamp01(
                (
                    trend_strength
                    + evidence_strength
                    + audience_clarity
                    + distribution_fit
                    + monetization
                    + novelty
                    + (1.0 - execution_risk)
                )
                / 7.0
            )
            final_score = _clamp01(
                trend_strength
                + audience_clarity
                + distribution_fit
                + build_feasibility
                + monetization
                + novelty
                - execution_risk
            )
            score_breakdowns[idea_id] = {
                "trend_strength": round(trend_strength, 3),
                "evidence_strength": round(evidence_strength, 3),
                "audience_clarity": round(audience_clarity, 3),
                "distribution_fit": round(distribution_fit, 3),
                "build_feasibility": round(build_feasibility, 3),
                "monetization_potential": round(monetization, 3),
                "novelty": round(novelty, 3),
                "execution_risk": round(execution_risk, 3),
                "confidence": round(confidence, 3),
                "final_idea_score": round(final_score, 3),
            }
            ideas.append(
                {
                    "idea_id": idea_id,
                    "topic_id": topic_id,
                    "idea_type": idea_type,
                    "title": f"{topic.canonical_title}: {idea_type.upper()} Play",
                    "one_liner": (hooks[0] if hooks else f"Convert {topic.canonical_title} momentum into a {idea_type} offer.")[:220],
                    "problem_statement": f"Audience demand is rising around '{topic.canonical_title}', but execution options are fragmented.",
                    "target_audience": _audience_for_source(dominant_source),
                    "distribution_channel": _distribution_for_type(idea_type, dominant_source),
                    "evidence": evidence_links.get(topic_id, []),
                    "novelty_angle": f"Blend {source_count} independent signals to avoid single-source noise.",
                    "build_scope": _build_scope_for_type(idea_type),
                    "time_to_value_days": _ttv_for_type(idea_type),
                    "confidence": round(confidence, 3),
                    "risks": [
                        "Signal reverses faster than build timeline",
                        "Audience intent may not convert to paid demand",
                    ],
                    "next_step": "Ship a scoped pilot and collect first 10 user responses within 7 days.",
                }
            )

    grouped_ideas: dict[str, list[dict]] = defaultdict(list)
    for idea in ideas:
        topic = topics_by_id.get(idea["topic_id"])
        key = _extract_theme(topic.canonical_title if topic else "")
        grouped_ideas[key].append(idea)

    idea_groups: list[dict] = []
    for theme, group_ideas in sorted(grouped_ideas.items(), key=lambda item: len(item[1]), reverse=True)[:8]:
        group_scores = [float(score_breakdowns.get(idea["idea_id"], {}).get("final_idea_score", 0.0)) for idea in group_ideas]
        group_score = round(sum(group_scores) / max(1, len(group_scores)), 3)
        idea_groups.append(
            {
                "group_id": str(uuid4()),
                "theme_name": theme.replace("-", " ").title(),
                "thesis": f"Demand around '{theme}' can be converted into a portfolio of fast offers.",
                "why_now": "Cross-source trend acceleration and low competitive density in practical execution assets.",
                "included_idea_ids": [idea["idea_id"] for idea in group_ideas],
                "included_topic_ids": sorted({idea["topic_id"] for idea in group_ideas}),
                "market_window": "30-90 days",
                "execution_sequence": [
                    "Launch one content wedge",
                    "Productize repeat requests into lightweight app",
                    "Package repeat workflow into subscription offer",
                ],
                "group_score": group_score,
            }
        )

    big_calls: list[dict] = []
    for group in sorted(idea_groups, key=lambda row: float(row.get("group_score", 0.0)), reverse=True)[:7]:
        score = _clamp01(float(group.get("group_score", 0.0)))
        big_calls.append(
            {
                "call_id": str(uuid4()),
                "headline": f"Prioritize {group['theme_name']} as a multi-format growth lane",
                "bet_type": "hybrid",
                "thesis": group["thesis"],
                "supporting_groups": [group["group_id"]],
                "expected_upside": "Build a repeatable audience-to-product funnel with measurable weekly output.",
                "key_assumptions": [
                    "Signal remains above baseline for 6+ weeks",
                    "Pilot audience converts to at least 5% email opt-in",
                ],
                "kill_criteria": [
                    "No meaningful user pull after two launch attempts",
                    "Acquisition cost exceeds target after week 4",
                ],
                "90_day_plan": [
                    "Days 1-30: ship one pilot and instrument funnel",
                    "Days 31-60: launch MVP and validate retention",
                    "Days 61-90: package offer and scale acquisition",
                ],
                "owner_profile": "builder-operator comfortable with content + product execution",
                "conviction_score": round(score, 3),
            }
        )

    recommended_next_actions = [f"Start: {call['headline']}" for call in big_calls[:3]]

    return {
        "topics": topics_payload,
        "ideas": ideas,
        "idea_groups": idea_groups,
        "big_calls": big_calls,
        "score_breakdowns": score_breakdowns,
        "evidence_links": dict(evidence_links),
        "recommended_next_actions": recommended_next_actions,
    }
