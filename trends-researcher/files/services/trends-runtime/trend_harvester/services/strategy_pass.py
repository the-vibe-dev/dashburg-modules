from __future__ import annotations

import json
from uuid import uuid4

from trend_harvester.config import get_settings
from trend_harvester.services.llm import LLMAnalyzer
from trend_harvester.services.openai_client import openai_structured_json
from trend_harvester.services.openai_key_store import openai_api_key_status


def _as_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for row in value:
        if isinstance(row, dict):
            out.append(row)
    return out


def _clean_text(value: object, max_len: int = 280) -> str:
    return str(value or "").strip()[:max_len]


def _safe_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _sanitize_ideas(rows: list[dict], fallback: list[dict]) -> list[dict]:
    if not rows:
        return fallback
    out: list[dict] = []
    for row in rows[:150]:
        idea_type = _clean_text(row.get("idea_type"), 16).lower()
        if idea_type not in {"video", "app", "saas"}:
            continue
        topic_id = _clean_text(row.get("topic_id"), 64)
        if not topic_id:
            continue
        out.append(
            {
                "idea_id": _clean_text(row.get("idea_id"), 64) or str(uuid4()),
                "topic_id": topic_id,
                "idea_type": idea_type,
                "title": _clean_text(row.get("title"), 220) or f"{topic_id}: {idea_type}",
                "one_liner": _clean_text(row.get("one_liner"), 260),
                "problem_statement": _clean_text(row.get("problem_statement"), 360),
                "target_audience": _clean_text(row.get("target_audience"), 180),
                "distribution_channel": _clean_text(row.get("distribution_channel"), 180),
                "evidence": _as_list(row.get("evidence")),
                "novelty_angle": _clean_text(row.get("novelty_angle"), 200),
                "build_scope": _clean_text(row.get("build_scope"), 12) or "medium",
                "time_to_value_days": max(1, min(365, int(float(row.get("time_to_value_days", 14))))),
                "confidence": _safe_score(row.get("confidence")),
                "risks": [str(x).strip()[:160] for x in (row.get("risks") if isinstance(row.get("risks"), list) else [])[:5] if str(x).strip()],
                "next_step": _clean_text(row.get("next_step"), 220),
            }
        )
    return out if out else fallback


def _sanitize_groups(rows: list[dict], fallback: list[dict]) -> list[dict]:
    if not rows:
        return fallback
    out: list[dict] = []
    for row in rows[:20]:
        out.append(
            {
                "group_id": _clean_text(row.get("group_id"), 64) or str(uuid4()),
                "theme_name": _clean_text(row.get("theme_name"), 140) or "Untitled Group",
                "thesis": _clean_text(row.get("thesis"), 360),
                "why_now": _clean_text(row.get("why_now"), 360),
                "included_idea_ids": [str(x).strip()[:64] for x in (row.get("included_idea_ids") if isinstance(row.get("included_idea_ids"), list) else [])[:200] if str(x).strip()],
                "included_topic_ids": [str(x).strip()[:64] for x in (row.get("included_topic_ids") if isinstance(row.get("included_topic_ids"), list) else [])[:200] if str(x).strip()],
                "market_window": _clean_text(row.get("market_window"), 80),
                "execution_sequence": [str(x).strip()[:160] for x in (row.get("execution_sequence") if isinstance(row.get("execution_sequence"), list) else [])[:8] if str(x).strip()],
                "group_score": _safe_score(row.get("group_score")),
            }
        )
    return out if out else fallback


def _sanitize_big_calls(rows: list[dict], fallback: list[dict]) -> list[dict]:
    if not rows:
        return fallback
    out: list[dict] = []
    for row in rows[:10]:
        out.append(
            {
                "call_id": _clean_text(row.get("call_id"), 64) or str(uuid4()),
                "headline": _clean_text(row.get("headline"), 220) or "Untitled Call",
                "bet_type": _clean_text(row.get("bet_type"), 24) or "hybrid",
                "thesis": _clean_text(row.get("thesis"), 360),
                "supporting_groups": [str(x).strip()[:64] for x in (row.get("supporting_groups") if isinstance(row.get("supporting_groups"), list) else [])[:30] if str(x).strip()],
                "expected_upside": _clean_text(row.get("expected_upside"), 280),
                "key_assumptions": [str(x).strip()[:180] for x in (row.get("key_assumptions") if isinstance(row.get("key_assumptions"), list) else [])[:8] if str(x).strip()],
                "kill_criteria": [str(x).strip()[:180] for x in (row.get("kill_criteria") if isinstance(row.get("kill_criteria"), list) else [])[:8] if str(x).strip()],
                "90_day_plan": [str(x).strip()[:180] for x in (row.get("90_day_plan") if isinstance(row.get("90_day_plan"), list) else [])[:10] if str(x).strip()],
                "owner_profile": _clean_text(row.get("owner_profile"), 180),
                "conviction_score": _safe_score(row.get("conviction_score")),
            }
        )
    return out if out else fallback


def _idea_score_breakdown(idea: dict) -> dict:
    confidence = _safe_score(idea.get("confidence"))
    execution_risk = 1.0 - confidence * 0.75
    build_scope = str(idea.get("build_scope", "medium")).lower()
    build_feasibility = 0.82 if build_scope == "small" else 0.65 if build_scope == "medium" else 0.45
    monetization = 0.55 if idea.get("idea_type") == "video" else 0.72 if idea.get("idea_type") == "app" else 0.83
    trend_strength = max(0.35, min(0.95, confidence + 0.05))
    evidence_strength = max(0.2, min(1.0, len(_as_list(idea.get("evidence"))) / 5.0))
    audience_clarity = max(0.3, min(1.0, confidence + 0.08))
    distribution_fit = max(0.3, min(1.0, confidence + 0.03))
    novelty = max(0.25, min(0.9, confidence + 0.02))
    final_score = max(0.0, min(1.0, trend_strength + audience_clarity + distribution_fit + build_feasibility + monetization + novelty - execution_risk))
    return {
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


def _update_phase(
    phase_status: dict[str, str],
    phase: str,
    status: str,
    progress_cb,
    *,
    error: str = "",
) -> None:
    phase_status[phase] = status
    if progress_cb is None:
        return
    payload = {"phase": phase, "status": status}
    if error:
        payload["error"] = error[:240]
    try:
        progress_cb(payload)
    except Exception:
        return


def _emit_progress(progress_cb, payload: dict) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(payload)
    except Exception:
        return


async def run_multiphase_strategy(seed: dict, *, require_openai: bool = True, progress_cb=None) -> dict:
    quick_topics = _as_list(seed.get("topics"))
    quick_ideas = _as_list(seed.get("ideas"))
    quick_groups = _as_list(seed.get("idea_groups"))
    quick_calls = _as_list(seed.get("big_calls"))
    if not quick_topics:
        return {
            "ideas": quick_ideas,
            "idea_groups": quick_groups,
            "big_calls": quick_calls,
            "score_breakdowns": seed.get("score_breakdowns", {}),
            "evidence_links": seed.get("evidence_links", {}),
            "recommended_next_actions": seed.get("recommended_next_actions", []),
            "phase_status": {"mode": "fallback", "reason": "no_topics"},
        }

    settings = get_settings()
    analyzer = LLMAnalyzer(settings)
    topic_seed = [
        {
            "topic_id": _clean_text(t.get("topic_id"), 64),
            "title": _clean_text(t.get("title"), 220),
            "summary": _clean_text(t.get("summary"), 360),
            "source_count": int(t.get("source_count", 1) or 1),
            "research_angles": (t.get("research_angles") if isinstance(t.get("research_angles"), list) else [])[:3],
        }
        for t in quick_topics[:25]
    ]

    phase_status: dict[str, str] = {}
    use_openai = bool(settings.openai_strategy_enabled and require_openai)
    if use_openai:
        key_status = openai_api_key_status()
        if not bool(key_status.get("configured")):
            raise RuntimeError("OpenAI API key is required for strategy pass")

    # Phase 1: topic interpretation
    _update_phase(phase_status, "phase1", "running", progress_cb)
    phase1_prompt = {
        "topics": topic_seed,
        "task": "Interpret each topic. For each topic_id return trend_classification (fad|emerging|persistent), opportunity_hints {video,app,saas}.",
    }
    if use_openai:
        _emit_progress(progress_cb, {"phase": "phase1", "event": "api_call_started", "provider": "openai"})
        phase1 = await openai_structured_json(
            system_prompt="Return strict JSON object only with key topic_interpretations as array.",
            user_prompt=json.dumps(phase1_prompt, ensure_ascii=True),
            temperature=0.1,
            max_tokens=2200,
        )
        _emit_progress(progress_cb, {"phase": "phase1", "event": "api_call_succeeded", "provider": "openai"})
    else:
        _emit_progress(progress_cb, {"phase": "phase1", "event": "api_call_started", "provider": "ollama"})
        phase1 = await analyzer.structured_json(
            system_prompt="Return strict JSON with key topic_interpretations as an array. No markdown.",
            user_prompt=json.dumps(phase1_prompt, ensure_ascii=True),
            temperature=0.2,
            num_predict=1200,
        )
        _emit_progress(progress_cb, {"phase": "phase1", "event": "api_call_succeeded", "provider": "ollama"})
    _update_phase(phase_status, "phase1", "ok", progress_cb)

    # Phase 2: idea generation
    _update_phase(phase_status, "phase2", "running", progress_cb)
    phase2_prompt = {
        "topic_interpretations": _as_list(phase1.get("topic_interpretations")),
        "topics": topic_seed,
        "task": (
            "Generate practical idea_candidates with strict fields: "
            "idea_id,topic_id,idea_type,title,one_liner,problem_statement,target_audience,"
            "distribution_channel,evidence,novelty_angle,build_scope,time_to_value_days,confidence,risks,next_step."
            " Only generate app/saas ideas when evidence supports product demand; do not force all idea_types per topic."
        ),
    }
    if use_openai:
        _emit_progress(progress_cb, {"phase": "phase2", "event": "api_call_started", "provider": "openai"})
        phase2 = await openai_structured_json(
            system_prompt=(
                "Return strict JSON object with key idea_candidates array. "
                "Prioritize originality and usefulness; reject generic template text."
            ),
            user_prompt=json.dumps(phase2_prompt, ensure_ascii=True),
            temperature=0.2,
            max_tokens=3600,
        )
        _emit_progress(progress_cb, {"phase": "phase2", "event": "api_call_succeeded", "provider": "openai"})
    else:
        _emit_progress(progress_cb, {"phase": "phase2", "event": "api_call_started", "provider": "ollama"})
        phase2 = await analyzer.structured_json(
            system_prompt="Return strict JSON with key idea_candidates as an array. No markdown.",
            user_prompt=json.dumps(phase2_prompt, ensure_ascii=True),
            temperature=0.35,
            num_predict=2200,
        )
        _emit_progress(progress_cb, {"phase": "phase2", "event": "api_call_succeeded", "provider": "ollama"})
    _update_phase(phase_status, "phase2", "ok", progress_cb)
    ideas = _sanitize_ideas(_as_list(phase2.get("idea_candidates")), quick_ideas)
    # Selective-by-fit: do not force all types per topic in final artifact.
    filtered_ideas: list[dict] = []
    seen_signatures: set[str] = set()
    per_topic_counts: dict[str, int] = {}
    for idea in ideas:
        topic_id = str(idea.get("topic_id", ""))
        if not topic_id:
            continue
        if per_topic_counts.get(topic_id, 0) >= 2:
            continue
        title_key = _clean_text(idea.get("title"), 140).lower()
        one_liner_key = _clean_text(idea.get("one_liner"), 140).lower()
        signature = f"{topic_id}|{idea.get('idea_type')}|{title_key}|{one_liner_key}"
        if signature in seen_signatures:
            continue
        if not idea.get("problem_statement") or not idea.get("target_audience") or not idea.get("next_step"):
            continue
        filtered_ideas.append(idea)
        seen_signatures.add(signature)
        per_topic_counts[topic_id] = per_topic_counts.get(topic_id, 0) + 1
    ideas = filtered_ideas or ideas

    # Phase 3: grouping and synthesis
    _update_phase(phase_status, "phase3", "running", progress_cb)
    phase3_prompt = {
        "ideas": ideas[:120],
        "task": (
            "Group ideas into 3-8 groups and return idea_groups with strict fields: "
            "group_id,theme_name,thesis,why_now,included_idea_ids,included_topic_ids,market_window,execution_sequence,group_score."
        ),
    }
    if use_openai:
        _emit_progress(progress_cb, {"phase": "phase3", "event": "api_call_started", "provider": "openai"})
        phase3 = await openai_structured_json(
            system_prompt="Return strict JSON object with key idea_groups as array. No markdown.",
            user_prompt=json.dumps(phase3_prompt, ensure_ascii=True),
            temperature=0.15,
            max_tokens=2400,
        )
        _emit_progress(progress_cb, {"phase": "phase3", "event": "api_call_succeeded", "provider": "openai"})
    else:
        _emit_progress(progress_cb, {"phase": "phase3", "event": "api_call_started", "provider": "ollama"})
        phase3 = await analyzer.structured_json(
            system_prompt="Return strict JSON with key idea_groups as an array. No markdown.",
            user_prompt=json.dumps(phase3_prompt, ensure_ascii=True),
            temperature=0.2,
            num_predict=1600,
        )
        _emit_progress(progress_cb, {"phase": "phase3", "event": "api_call_succeeded", "provider": "ollama"})
    _update_phase(phase_status, "phase3", "ok", progress_cb)
    groups = _sanitize_groups(_as_list(phase3.get("idea_groups")), quick_groups)

    # Phase 4: big calls
    _update_phase(phase_status, "phase4", "running", progress_cb)
    phase4_prompt = {
        "idea_groups": groups,
        "ideas": ideas[:120],
        "task": (
            "Return 3-7 big_calls with strict fields: "
            "call_id,headline,bet_type,thesis,supporting_groups,expected_upside,key_assumptions,kill_criteria,90_day_plan,owner_profile,conviction_score. "
            "Also include recommended_next_actions list."
        ),
    }
    if use_openai:
        _emit_progress(progress_cb, {"phase": "phase4", "event": "api_call_started", "provider": "openai"})
        phase4 = await openai_structured_json(
            system_prompt=(
                "Return strict JSON with keys big_calls (array), recommended_next_actions (array), "
                "and optional review_notes (array)."
            ),
            user_prompt=json.dumps(phase4_prompt, ensure_ascii=True),
            temperature=0.1,
            max_tokens=2600,
        )
        _emit_progress(progress_cb, {"phase": "phase4", "event": "api_call_succeeded", "provider": "openai"})
    else:
        _emit_progress(progress_cb, {"phase": "phase4", "event": "api_call_started", "provider": "ollama"})
        phase4 = await analyzer.structured_json(
            system_prompt="Return strict JSON with keys big_calls (array) and recommended_next_actions (array). No markdown.",
            user_prompt=json.dumps(phase4_prompt, ensure_ascii=True),
            temperature=0.15,
            num_predict=1800,
        )
        _emit_progress(progress_cb, {"phase": "phase4", "event": "api_call_succeeded", "provider": "ollama"})
    _update_phase(phase_status, "phase4", "ok", progress_cb)
    big_calls = _sanitize_big_calls(_as_list(phase4.get("big_calls")), quick_calls)

    score_breakdowns = {}
    for idea in ideas:
        idea_id = _clean_text(idea.get("idea_id"), 64)
        if not idea_id:
            continue
        score_breakdowns[idea_id] = _idea_score_breakdown(idea)

    next_actions = phase4.get("recommended_next_actions")
    if not isinstance(next_actions, list):
        next_actions = []
    recommended_next_actions = [str(x).strip()[:220] for x in next_actions[:8] if str(x).strip()]
    if not recommended_next_actions:
        recommended_next_actions = [f"Start: {row.get('headline', 'priority call')}" for row in big_calls[:3]]

    ideas_by_type = {"video": [], "app": [], "saas": []}
    for idea in ideas:
        idea_type = str(idea.get("idea_type", "")).lower()
        if idea_type in ideas_by_type:
            ideas_by_type[idea_type].append(idea)
    review_notes_raw = phase4.get("review_notes") if isinstance(phase4, dict) else []
    if not isinstance(review_notes_raw, list):
        review_notes_raw = []
    review_notes = [str(x).strip()[:240] for x in review_notes_raw[:12] if str(x).strip()]

    return {
        "ideas": ideas,
        "ideas_by_type": ideas_by_type,
        "idea_groups": groups,
        "big_calls": big_calls,
        "score_breakdowns": score_breakdowns,
        "evidence_links": seed.get("evidence_links", {}),
        "recommended_next_actions": recommended_next_actions,
        "review_notes": review_notes,
        "phase_status": {"mode": ("openai_multiphase" if use_openai else "llm_multiphase"), **phase_status},
    }
