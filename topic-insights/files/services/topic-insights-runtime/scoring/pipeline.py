from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from collections import Counter

from clustering.pipeline import get_current_cluster_map
from connectors.x_trends_playwright import parse_post_count_value
from scoring.competition_scan import scan_competition
from scoring.load_config import load_scoring_config
from scoring.monetization_score import monetization_score
from scoring.opportunity_score import competition_penalty, final_opportunity, normalize_engagement, pain_score
from scoring.simplicity_score import simplicity_score
from storage.models import ExtractedPain, PainCluster
from storage.repository import get_raw_posts_by_ids


@dataclass
class _MergedCluster:
    cluster_id: str
    cluster_label: str
    canonical_label: str
    pain_count: int
    pains: list[ExtractedPain]
    source_clusters: list[PainCluster]


def _canonicalize_label(label: str) -> str:
    lowered = (label or "").lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _merge_by_canonical_label(
    clusters: list[PainCluster],
    cmap: dict[str, list[ExtractedPain]],
) -> list[_MergedCluster]:
    merged: dict[str, _MergedCluster] = {}
    for c in clusters:
        canonical = _canonicalize_label(c.cluster_label)
        key = canonical or c.cluster_id
        group = merged.get(key)
        if group is None:
            merged[key] = _MergedCluster(
                cluster_id=c.cluster_id,
                cluster_label=c.cluster_label,
                canonical_label=canonical,
                pain_count=max(1, int(c.pain_count or 0)),
                pains=list(cmap.get(c.cluster_id, [])),
                source_clusters=[c],
            )
        else:
            group.pain_count += max(0, int(c.pain_count or 0))
            group.pains.extend(cmap.get(c.cluster_id, []))
            group.source_clusters.append(c)
            # Preserve longest representative label for readability.
            if len(c.cluster_label or "") > len(group.cluster_label or ""):
                group.cluster_label = c.cluster_label
    return list(merged.values())


def _theme_boost(canonical_label: str, pains: list[ExtractedPain], cfg: dict) -> float:
    boosts = cfg.get("theme_boosts") or []
    if not boosts:
        return 0.0

    text_parts = [canonical_label]
    for p in pains[:20]:
        text_parts.append((p.pain_summary or "").lower())
        text_parts.extend([(k or "").lower() for k in (p.frustration_keywords or [])[:8]])
    haystack = "\n".join(text_parts)

    best = 0.0
    for rule in boosts:
        keywords = [str(k).lower() for k in (rule.get("keywords") or []) if str(k).strip()]
        if not keywords:
            continue
        if any(k in haystack for k in keywords):
            best = max(best, float(rule.get("boost") or 0.0))
    return max(0.0, min(0.2, best))


def _collect_source_signals(pains: list[ExtractedPain]) -> tuple[list[str], float]:
    raw_ids = [p.raw_post_id for p in pains if p.raw_post_id]
    if not raw_ids:
        return [], 0.0

    rows = get_raw_posts_by_ids(raw_ids)
    source_counts: Counter[str] = Counter()
    x_best_rank: int | None = None
    x_best_post_count: float | None = None
    for row in rows:
        src = str(row.source or "").strip().lower()
        if not src:
            continue
        source_counts[src] += 1
        if src != "x":
            continue
        metrics = (row.metadata_ or {}).get("metrics") or {}
        rank = metrics.get("rank")
        if isinstance(rank, (int, float)):
            val = int(rank)
            if x_best_rank is None or val < x_best_rank:
                x_best_rank = val
        post_count_text = str(metrics.get("post_count_text") or "")
        parsed = parse_post_count_value(post_count_text)
        if parsed is not None and (x_best_post_count is None or parsed > x_best_post_count):
            x_best_post_count = parsed

    sources = list(source_counts.keys())
    x_bonus_points = 0.0
    if source_counts.get("x", 0) > 0:
        x_bonus_points += 18.0
        if x_best_rank is not None:
            x_bonus_points += max(0.0, 15.0 - float(x_best_rank))
        if x_best_post_count is not None:
            if x_best_post_count >= 100_000:
                x_bonus_points += 6.0
            elif x_best_post_count >= 10_000:
                x_bonus_points += 4.0
            elif x_best_post_count >= 1_000:
                x_bonus_points += 2.0
        if any(s in {"reddit", "web", "youtube", "youtube_comment", "reddit_comment"} for s in sources if s != "x"):
            x_bonus_points += 8.0

    return sources, x_bonus_points / 100.0


def score_clusters(clusters: list[PainCluster], run_id: str | None = None) -> list[PainCluster]:
    cfg = load_scoring_config()
    log = logging.getLogger(__name__)
    if not clusters:
        return []

    w_pain = cfg["weights"]["pain"]
    w_comp = cfg["weights"]["competition_penalty"]
    w_final = cfg["weights"]["final"]
    rules = cfg.get("simplicity_rules", {})

    cmap = get_current_cluster_map()
    merged = _merge_by_canonical_label(clusters, cmap)
    max_cluster_size = max((m.pain_count for m in merged), default=1)
    scored: list[PainCluster] = []

    for m in merged:
        pains = m.pains
        if pains:
            avg_int = sum(float(p.emotional_intensity or 0.0) for p in pains) / max(1, len(pains))
            workaround_rate = sum(1 for p in pains if p.workaround_detected) / max(1, len(pains))
            urgency_rate = sum(float(p.urgency_signal or 0.0) for p in pains) / max(1, len(pains))
        else:
            # Fallback to persisted cluster averages when in-memory map is not available.
            avg_int = sum(float(s.avg_intensity or 0.0) for s in m.source_clusters) / max(1, len(m.source_clusters))
            workaround_rate = 0.0
            urgency_rate = 0.0

        pseudo_engagement = (avg_int * 100.0) + (workaround_rate * 80.0) + (urgency_rate * 60.0)
        freq = m.pain_count / max(1, max_cluster_size)

        pscore = pain_score(
            normalized_engagement=normalize_engagement(pseudo_engagement),
            intensity=min(1.0, avg_int),
            frequency=min(1.0, freq),
            workaround=(workaround_rate >= 0.25),
            weights=w_pain,
        )

        competitor_count = 0.0
        seo_sat = 0.0
        funding = 0.0
        if cfg.get("competition_scan", {}).get("enabled", True):
            try:
                sig = scan_competition(m.cluster_label)
                competitor_count = float(sig.competitor_count_norm)
                seo_sat = float(sig.seo_saturation_norm)
                funding = float(sig.funding_signal_norm)
            except Exception as exc:
                log.warning("competition_scan_failed label=%s error=%s", m.cluster_label, exc)

        comp_pen = competition_penalty(competitor_count, seo_sat, funding, w_comp)
        simp = simplicity_score(m.cluster_label, rules)
        mon = monetization_score(m.cluster_label)
        boost = _theme_boost(m.canonical_label, pains, cfg)
        top_sources, x_signal_boost = _collect_source_signals(pains)

        final = final_opportunity(pscore, simp, mon, comp_pen, w_final)
        final = max(0.0, min(1.0, final + boost + x_signal_boost))

        scored.append(
            PainCluster(
                cluster_id=m.cluster_id,
                run_id=run_id,
                cluster_label=m.cluster_label,
                pain_count=m.pain_count,
                avg_intensity=float(avg_int),
                avg_engagement=float(normalize_engagement(pseudo_engagement)),
                top_sources=top_sources[:4],
                competition_signal=float(competitor_count),
                monetization_signal=float(mon),
                simplicity_score=float(simp),
                pain_score=float(pscore),
                competition_penalty=float(comp_pen),
                opportunity_score=float(final * cfg["scales"]["opportunity_score_max"]),
            )
        )

    scored.sort(key=lambda x: x.opportunity_score, reverse=True)
    return scored
