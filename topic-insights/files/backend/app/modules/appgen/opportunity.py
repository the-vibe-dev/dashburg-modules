from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


IDEA_TYPES = ("video", "app", "saas")

_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "from",
    "this",
    "into",
    "your",
    "about",
    "when",
    "have",
    "will",
    "how",
    "are",
    "has",
    "you",
    "they",
    "their",
    "what",
    "why",
    "can",
    "not",
    "all",
}


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        out = value.strip()
        return out if out else default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def classify_idea_type(idea: dict[str, Any]) -> str:
    explicit = _text(idea.get("idea_type"), "").lower()
    if explicit in IDEA_TYPES:
        return explicit
    category = _text(idea.get("category") or idea.get("vertical") or idea.get("type"), "").lower()
    title = _normalize_whitespace(_text(idea.get("title") or idea.get("idea_name") or idea.get("name"), ""))
    summary = _normalize_whitespace(_text(idea.get("summary") or idea.get("one_liner") or idea.get("description"), ""))
    blob = f"{category} {title} {summary}"
    if any(token in blob for token in ("video", "youtube", "short", "hook", "thumbnail", "script")):
        return "video"
    if any(token in blob for token in ("saas", "b2b", "enterprise", "workflow", "subscription")):
        return "saas"
    return "app"


def _extract_first_build_step(idea: dict[str, Any], idea_type: str) -> str:
    step = _text(idea.get("first_build_step") or idea.get("mvp_step") or idea.get("next_step"))
    if step:
        return step
    if idea_type == "video":
        return "Draft the hook, 5-beat outline, and publish one test video."
    if idea_type == "saas":
        return "Build a narrow workflow MVP and validate willingness to pay with 5 target buyers."
    return "Build a thin MVP for one user segment and test with 3-5 users this week."


def _extract_why_now(idea: dict[str, Any]) -> str:
    why_now = _text(idea.get("why_now") or idea.get("timing_reason") or idea.get("trend_reason"))
    if why_now:
        return why_now
    trend = _text(idea.get("trend_alignment") or idea.get("trend_signal"))
    if trend:
        return f"Trend signal: {trend}"
    return "Repeated signal frequency indicates current demand."


def _extract_problem_summary(idea: dict[str, Any]) -> str:
    return _text(
        idea.get("problem_summary")
        or idea.get("problem")
        or idea.get("core_problem")
        or idea.get("pain_summary")
        or idea.get("user_problem"),
        "Problem not specified.",
    )


def _extract_target_user(idea: dict[str, Any]) -> str:
    return _text(idea.get("target_user") or idea.get("target") or idea.get("audience") or idea.get("icp"), "General users")


def _extract_title(idea: dict[str, Any]) -> str:
    return _text(idea.get("title") or idea.get("idea_name") or idea.get("name") or idea.get("id"), "Untitled opportunity")


def _extract_summary(idea: dict[str, Any]) -> str:
    return _text(
        idea.get("summary")
        or idea.get("one_liner")
        or idea.get("description")
        or idea.get("solution_summary")
        or idea.get("hook"),
        "No summary provided.",
    )


def _base_score(idea: dict[str, Any]) -> float:
    for key in ("score", "opportunity_score", "overall_score", "would_build_confidence", "confidence", "confidence_score"):
        if key in idea:
            raw = _num(idea.get(key), 0.0)
            if key.startswith("confidence") or key == "would_build_confidence":
                if raw <= 1:
                    return max(0.0, min(10.0, raw * 10.0))
            return max(0.0, min(10.0, raw))
    return 0.0


def _keyword_hits(text_blob: str, terms: list[str]) -> float:
    hits = 0
    for term in terms:
        if term in text_blob:
            hits += 1
    return float(hits)


def score_components(idea: dict[str, Any], idea_type: str) -> dict[str, float]:
    title = _normalize_whitespace(_extract_title(idea))
    summary = _normalize_whitespace(_extract_summary(idea))
    problem = _normalize_whitespace(_extract_problem_summary(idea))
    blob = f"{title} {summary} {problem}"
    if idea_type == "video":
        return {
            "hook_strength": min(10.0, _num(idea.get("hook_strength"), 0.0) or _keyword_hits(blob, ["you won't", "mistake", "secret", "before", "why"]) * 1.5 + 3.0),
            "trend_alignment": min(10.0, _num(idea.get("trend_alignment"), 0.0) or _keyword_hits(blob, ["trend", "new", "viral", "surge"]) * 2.0 + 2.0),
            "repeatability": min(10.0, _num(idea.get("repeatability"), 0.0) or _keyword_hits(blob, ["series", "weekly", "template", "repeat"]) * 2.0 + 2.0),
            "production_ease": min(10.0, _num(idea.get("production_ease"), 0.0) or _keyword_hits(blob, ["simple", "quick", "short", "screen"]) * 2.0 + 2.0),
        }
    if idea_type == "saas":
        return {
            "operational_pain": min(10.0, _num(idea.get("operational_pain"), 0.0) or _keyword_hits(blob, ["manual", "workflow", "compliance", "ops", "broken"]) * 2.0 + 2.0),
            "willingness_to_pay": min(10.0, _num(idea.get("willingness_to_pay"), 0.0) or _keyword_hits(blob, ["cost", "revenue", "budget", "pricing", "b2b"]) * 1.8 + 2.5),
            "distribution_path": min(10.0, _num(idea.get("distribution_path"), 0.0) or _keyword_hits(blob, ["integration", "marketplace", "agency", "community"]) * 2.0 + 2.0),
            "defensibility": min(10.0, _num(idea.get("defensibility"), 0.0) or _keyword_hits(blob, ["data", "workflow lock", "moat", "switching"]) * 2.0 + 2.0),
        }
    return {
        "pain_severity": min(10.0, _num(idea.get("pain_severity"), 0.0) or _keyword_hits(blob, ["pain", "friction", "slow", "expensive", "error"]) * 2.0 + 2.0),
        "user_clarity": min(10.0, _num(idea.get("user_clarity"), 0.0) or (_keyword_hits(blob, ["freelancer", "team", "creator", "manager"]) * 2.0 + 2.0)),
        "mvp_feasibility": min(10.0, _num(idea.get("mvp_feasibility"), 0.0) or _keyword_hits(blob, ["mvp", "simple", "lightweight", "prototype"]) * 2.0 + 2.0),
        "monetization_potential": min(10.0, _num(idea.get("monetization_potential"), 0.0) or _keyword_hits(blob, ["subscription", "paid", "plan", "upgrade", "sell"]) * 2.0 + 2.0),
    }


def final_type_score(idea: dict[str, Any], idea_type: str) -> float:
    base = _base_score(idea)
    comps = score_components(idea, idea_type)
    component_avg = sum(comps.values()) / max(1, len(comps))
    return round((base * 0.45) + (component_avg * 0.55), 2)


def _evidence_rows(idea: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for key in ("evidence", "evidence_snippets", "supporting_evidence", "sources", "signals"):
        val = idea.get(key)
        if isinstance(val, list):
            for item in val:
                text = _text(item, "")
                if text:
                    evidence.append(text)
    snippet = _text(idea.get("evidence_snippet"), "")
    if snippet:
        evidence.append(snippet)
    return evidence[:8]


def normalize_opportunity(idea: dict[str, Any], *, source_run_id: str | None = None) -> dict[str, Any]:
    idea_type = classify_idea_type(idea)
    components = score_components(idea, idea_type)
    out = {
        "id": _text(idea.get("id") or idea.get("idea_id") or idea.get("uuid"), ""),
        "title": _extract_title(idea),
        "summary": _extract_summary(idea),
        "idea_type": idea_type,
        "problem_summary": _extract_problem_summary(idea),
        "target_user": _extract_target_user(idea),
        "why_now": _extract_why_now(idea),
        "first_build_step": _extract_first_build_step(idea, idea_type),
        "source_run_id": source_run_id or _text(idea.get("run_id") or idea.get("source_run_id"), ""),
        "cluster_id": _text(idea.get("cluster_id") or idea.get("cluster"), ""),
        "evidence": _evidence_rows(idea),
        "score_components": components,
        "score": final_type_score(idea, idea_type),
        "shortlist_rationale": {
            "winner_because": _text(idea.get("winner_because") or idea.get("differentiation") or idea.get("why_now"), "High pain, clear user, and feasible wedge."),
            "why_not_higher": _text(idea.get("why_not_higher") or idea.get("risk"), "Evidence depth or distribution path needs validation."),
        },
        "raw": idea,
    }
    return out


def dedupe_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = _normalize_whitespace(_text(row.get("title")))
        problem = _normalize_whitespace(_text(row.get("problem_summary")))
        title_tokens = " ".join(sorted(set(re.findall(r"[a-z0-9]{3,}", title)))[:8])
        key = f"{row.get('idea_type','app')}::{title_tokens or title}::{problem[:160]}"
        existing = by_key.get(key)
        if existing is None or _num(row.get("score"), 0.0) > _num(existing.get("score"), 0.0):
            by_key[key] = row
    ranked = sorted(by_key.values(), key=lambda item: _num(item.get("score"), 0.0), reverse=True)
    # Soft diversity cap: avoid one dominant theme occupying all top slots.
    theme_counts: Counter[str] = Counter()
    diverse: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    for row in ranked:
        problem = _normalize_whitespace(_text(row.get("problem_summary")))
        tokens = [token for token in re.findall(r"[a-z0-9]{4,}", problem) if token not in _STOPWORDS]
        theme_key = tokens[0] if tokens else "general"
        if theme_counts[theme_key] < 2:
            diverse.append(row)
            theme_counts[theme_key] += 1
        else:
            overflow.append(row)
    return diverse + overflow


def cluster_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        title = _normalize_whitespace(_text(row.get("title")))
        tokens = [token for token in re.findall(r"[a-z0-9]{4,}", title) if token not in _STOPWORDS]
        key = tokens[0] if tokens else _text(row.get("idea_type"), "app")
        buckets[f"{row.get('idea_type','app')}::{key}"].append(row)
    clusters: list[dict[str, Any]] = []
    for key, items in buckets.items():
        items_sorted = sorted(items, key=lambda item: _num(item.get("score"), 0.0), reverse=True)
        clusters.append(
            {
                "cluster_key": key,
                "idea_type": key.split("::", 1)[0],
                "size": len(items_sorted),
                "representative_title": _text(items_sorted[0].get("title"), "Untitled"),
                "avg_score": round(sum(_num(item.get("score"), 0.0) for item in items_sorted) / max(1, len(items_sorted)), 2),
                "items": items_sorted[:8],
            }
        )
    clusters.sort(key=lambda item: (item["size"], item["avg_score"]), reverse=True)
    return clusters


def compute_week_range(now: datetime | None = None) -> tuple[str, str]:
    ref = now or datetime.now(timezone.utc)
    end = datetime(ref.year, ref.month, ref.day, tzinfo=timezone.utc)
    start = end - timedelta(days=6)
    return start.date().isoformat(), end.date().isoformat()


def summarize_themes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        blob = f"{_normalize_whitespace(_text(row.get('title')))} {_normalize_whitespace(_text(row.get('problem_summary')))}"
        for token in re.findall(r"[a-z0-9]{4,}", blob):
            if token in _STOPWORDS:
                continue
            counter[token] += 1
    return [{"theme": token, "count": count} for token, count in counter.most_common(12)]
