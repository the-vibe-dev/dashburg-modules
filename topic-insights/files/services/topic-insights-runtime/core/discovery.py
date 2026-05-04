from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from core.config import settings
from extraction.llm import chat_json
from ingestion.reddit.search import reddit_search
from ingestion.web.search import web_search

DISCOVERY_SYSTEM = "You extract concise problem topics from noisy search results."
DISCOVERY_USER_TMPL = """Extract up to 10 concise topics (2-6 words each) that represent *problems/pain points* people have.

Rules:
- Topics must be phrased as a problem area, not a solution.
- Avoid duplicates and near-duplicates.
- Prefer everyday life problems (household, gardening, cooking, pets, parenting, car, freelancing).

Return JSON only: {{"topics": ["..."]}}
CONTENT:
{content}
"""

PAIN_QUERIES = [
    'site:reddit.com "why is it so hard"',
    'site:reddit.com "I hate when"',
    'site:reddit.com "does anyone else struggle"',
    '"there should be an app" problem',
    '"this is so annoying" how to',
    '"any tool for" problem',
]


@dataclass
class DiscoveredTopic:
    topic: str
    count: int


def _normalize_topics(topics: list[str], target: int) -> list[DiscoveredTopic]:
    norm: list[str] = []
    seen = set()
    for t in topics:
        cleaned = " ".join((t or "").strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        norm.append(cleaned)
    counts = Counter(norm)
    return [DiscoveredTopic(topic=t, count=counts[t]) for t in norm[:target]]


def _fallback_topics_from_chunks(chunks: list[str], target: int) -> list[DiscoveredTopic]:
    """LLM-free fallback so auto-run never hard fails when model is unavailable."""
    stop = {
        "this", "that", "with", "from", "your", "they", "have", "just", "what", "when", "where", "would",
        "could", "there", "about", "their", "them", "been", "were", "very", "some", "more", "into", "than",
        "then", "does", "dont", "cant", "wont", "need", "help", "how", "why", "hard", "hate", "struggle",
    }
    phrase_counter: Counter[str] = Counter()

    for text in chunks:
        words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9']+", (text or "").lower()) if len(w) >= 4 and w not in stop]
        for i in range(len(words) - 1):
            bi = f"{words[i]} {words[i + 1]}"
            phrase_counter[bi] += 1

    topics = [p for p, _ in phrase_counter.most_common(max(target * 3, 20))]
    # Shape into "problem-like" labels.
    normalized = [f"{t} challenges" for t in topics[:target]]
    return _normalize_topics(normalized, target)


def discover_topics(target: int = 20) -> list[DiscoveredTopic]:
    log = logging.getLogger(__name__)
    chunks: list[str] = []
    for q in PAIN_QUERIES[:4]:
        try:
            posts = reddit_search(q, limit=20)
            chunks.extend([p.text[:800] for p in posts if p.text])
        except Exception as exc:
            log.warning("discover_reddit_failed query=%s error=%s", q, exc)
        try:
            web = web_search(q, limit=15)
            chunks.extend([p.text[:800] for p in web if p.text])
        except Exception as exc:
            log.warning("discover_web_failed query=%s error=%s", q, exc)

    content = "\n\n---\n\n".join(chunks)[: settings.llm_max_input_chars]
    if not content.strip():
        return []

    try:
        data = chat_json(DISCOVERY_SYSTEM, DISCOVERY_USER_TMPL.format(content=content))
        topics = [t.strip() for t in (data.get("topics") or []) if isinstance(t, str) and t.strip()]
        result = _normalize_topics(topics, target)
        if result:
            return result
    except Exception as exc:
        log.warning("discover_llm_failed using_fallback error=%r", exc)

    fallback = _fallback_topics_from_chunks(chunks, target)
    if fallback:
        log.info("discover_fallback_topics count=%s", len(fallback))
    return fallback
