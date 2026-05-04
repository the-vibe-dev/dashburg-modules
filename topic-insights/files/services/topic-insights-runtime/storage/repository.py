from __future__ import annotations
from typing import Iterable, Sequence
from datetime import datetime
from sqlmodel import select
from sqlalchemy import func
from storage.db import get_session
from storage.models import RawPost, ExtractedPain, PainCluster, Idea, RunEvent, ApiCallLog

def upsert_raw_posts(posts: Sequence[RawPost]) -> None:
    with get_session() as s:
        for p in posts:
            existing = s.get(RawPost, p.id)
            if existing:
                existing.run_id = p.run_id or existing.run_id
                existing.text = p.text
                existing.engagement_score = p.engagement_score
                existing.metadata_ = p.metadata_
                existing.timestamp = p.timestamp
                existing.url = p.url
                existing.source = p.source
                existing.author = p.author
            else:
                s.add(p)
        s.commit()

def insert_pains(pains: Sequence[ExtractedPain]) -> None:
    with get_session() as s:
        for p in pains:
            if not s.get(ExtractedPain, p.pain_id):
                s.add(p)
        s.commit()

def insert_clusters(clusters: Sequence[PainCluster]) -> None:
    with get_session() as s:
        for c in clusters:
            if not s.get(PainCluster, c.cluster_id):
                s.add(c)
        s.commit()

def insert_ideas(ideas: Sequence[Idea]) -> None:
    with get_session() as s:
        for i in ideas:
            if not s.get(Idea, i.idea_id):
                s.add(i)
        s.commit()

def insert_run_event(ev: RunEvent) -> None:
    with get_session() as s:
        s.add(ev)
        s.commit()

def insert_api_call_log(ev: ApiCallLog) -> None:
    with get_session() as s:
        s.add(ev)
        s.commit()

def list_run_events(limit: int = 50) -> list[RunEvent]:
    with get_session() as s:
        q = select(RunEvent).order_by(RunEvent.created_at.desc()).limit(limit)
        return list(s.exec(q))

def get_counts() -> dict[str, int]:
    with get_session() as s:
        return {
            "raw_posts": s.exec(select(func.count()).select_from(RawPost)).one(),
            "pains": s.exec(select(func.count()).select_from(ExtractedPain)).one(),
            "clusters": s.exec(select(func.count()).select_from(PainCluster)).one(),
            "ideas": s.exec(select(func.count()).select_from(Idea)).one(),
        }

def rawpost_counts_by_source() -> dict[str, int]:
    with get_session() as s:
        q = select(RawPost.source, func.count()).group_by(RawPost.source)
        rows = s.exec(q).all()
        return {source: count for source, count in rows}

def provider_stats(limit: int = 100) -> list[ApiCallLog]:
    with get_session() as s:
        q = select(ApiCallLog).order_by(ApiCallLog.created_at.desc()).limit(limit)
        return list(s.exec(q))

def list_clusters(limit: int = 50, run_id: str | None = None) -> list[PainCluster]:
    with get_session() as s:
        q = select(PainCluster).order_by(PainCluster.opportunity_score.desc()).limit(limit)
        if run_id:
            q = select(PainCluster).where(PainCluster.run_id == run_id).order_by(PainCluster.opportunity_score.desc()).limit(limit)
        return list(s.exec(q))

def get_cluster(cluster_id: str) -> PainCluster | None:
    with get_session() as s:
        return s.get(PainCluster, cluster_id)

def list_ideas(cluster_id: str | None = None, limit: int = 100, run_id: str | None = None) -> list[Idea]:
    with get_session() as s:
        q = select(Idea)
        if run_id:
            q = q.where(Idea.run_id == run_id)
        if cluster_id:
            q = q.where(Idea.cluster_id == cluster_id)
        q = q.order_by(Idea.opportunity_score.desc()).limit(limit)
        return list(s.exec(q))


def list_clusters_all(limit: int = 200) -> list[PainCluster]:
    with get_session() as s:
        q = select(PainCluster).order_by(PainCluster.opportunity_score.desc(), PainCluster.created_at.desc()).limit(limit)
        return list(s.exec(q))


def find_pains_for_cluster_label(cluster_label: str, limit: int = 40) -> list[ExtractedPain]:
    """Best-effort DB-backed examples for a cluster label.

    Since pains are not persisted with cluster_id, retrieve by keyword overlap on pain_summary,
    ranked by urgency/intensity/workaround evidence.
    """
    tokens = [t.strip().lower() for t in cluster_label.replace('/', ' ').replace('-', ' ').split() if len(t.strip()) >= 3]
    tokens = tokens[:6]
    with get_session() as s:
        # Pull a recent window then rank in Python for portability across sqlite versions.
        base = list(
            s.exec(
                select(ExtractedPain)
                .order_by(ExtractedPain.created_at.desc())
                .limit(max(200, limit * 8))
            )
        )

    def _score(p: ExtractedPain) -> float:
        txt = (p.pain_summary or '').lower()
        overlap = sum(1 for t in tokens if t in txt)
        return (
            overlap * 2.0
            + float(p.emotional_intensity or 0.0) * 1.2
            + float(p.urgency_signal or 0.0) * 1.0
            + (0.5 if p.workaround_detected else 0.0)
        )

    ranked = sorted(base, key=_score, reverse=True)
    seen = set()
    out: list[ExtractedPain] = []
    # diversify by summary hash to avoid near-duplicates
    for p in ranked:
        summary = (p.pain_summary or '').strip().lower()
        if not summary:
            continue
        key = summary[:140]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def get_idea(idea_id: str) -> Idea | None:
    with get_session() as s:
        return s.get(Idea, idea_id)


def list_pains(topic: str | None = None, limit: int = 200, run_id: str | None = None) -> list[ExtractedPain]:
    with get_session() as s:
        q = select(ExtractedPain)
        if run_id:
            q = q.where(ExtractedPain.run_id == run_id)
        if topic:
            q = q.where(ExtractedPain.topic == topic)
        q = q.order_by(ExtractedPain.created_at.desc()).limit(limit)
        return list(s.exec(q))


def get_run_events_by_run_id(run_id: str, limit: int = 200) -> list[RunEvent]:
    with get_session() as s:
        q = (
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.created_at.asc())
            .limit(limit)
        )
        return list(s.exec(q))


def provider_stats_for_run(run_id: str, limit: int = 500) -> list[ApiCallLog]:
    with get_session() as s:
        q = (
            select(ApiCallLog)
            .where(ApiCallLog.run_id == run_id)
            .order_by(ApiCallLog.created_at.desc())
            .limit(limit)
        )
        return list(s.exec(q))


def get_raw_posts_by_ids(raw_post_ids: Sequence[str]) -> list[RawPost]:
    ids = [x for x in raw_post_ids if x]
    if not ids:
        return []
    with get_session() as s:
        q = select(RawPost).where(RawPost.id.in_(ids))
        return list(s.exec(q))
