from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    class _FallbackFuzz:
        @staticmethod
        def ratio(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio() * 100

    fuzz = _FallbackFuzz()


NORMALIZE_RE = re.compile(r"[^\w\s]")
WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    lowered = title.lower().strip()
    lowered = NORMALIZE_RE.sub(" ", lowered)
    return WHITESPACE_RE.sub(" ", lowered).strip()


@dataclass
class CandidateLike:
    title: str
    url: str


def similar_enough(a: str, b: str, threshold: float) -> bool:
    return fuzz.ratio(a, b) >= threshold


def cluster_candidates(items: list[dict], threshold: float) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for item in items:
        n_title = normalize_title(item["title"])
        attached = False
        for cluster in clusters:
            first = cluster[0]
            first_title = normalize_title(first["title"])
            same_url = any(x.get("url") == item.get("url") for x in cluster)
            if same_url or _should_merge(item, first, n_title, first_title, threshold):
                cluster.append(item)
                attached = True
                break
        if not attached:
            clusters.append([item])
    return clusters


def _should_merge(item: dict, first: dict, n_title: str, first_title: str, threshold: float) -> bool:
    source_a = str(item.get("source", ""))
    source_b = str(first.get("source", ""))

    if source_a == "trends" and source_b == "trends":
        # Prevent broad fuzzy collapsing of many trend headlines.
        return n_title == first_title

    if source_a == "trends" or source_b == "trends":
        # Require slightly stronger match for cross-source trend merges.
        return similar_enough(n_title, first_title, min(threshold + 5.0, 98.0))

    return similar_enough(n_title, first_title, threshold)
