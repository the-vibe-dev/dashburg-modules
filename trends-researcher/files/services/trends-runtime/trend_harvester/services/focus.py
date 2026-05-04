from __future__ import annotations

import re
from typing import Iterable

_STOPWORDS = {
    "a", "an", "and", "or", "the", "to", "of", "in", "on", "for", "with", "at", "by", "from", "is", "are", "was", "were",
    "be", "this", "that", "these", "those", "it", "its", "as", "into", "about", "over", "under", "after", "before",
    "how", "why", "what", "who", "when", "where", "vs", "via", "new", "latest", "today", "now",
}

_EPL_KEYWORDS = {
    "english premier league", "premier league", "epl", "soccer", "football", "matchday", "title race", "relegation", "golden boot",
    "arsenal", "liverpool", "chelsea", "manchester city", "man city", "manchester united", "man utd", "tottenham", "spurs",
    "newcastle", "aston villa", "west ham", "brighton", "wolves", "everton", "fulham", "brentford", "crystal palace",
    "nottingham forest", "bournemouth", "burnley", "leicester", "southampton", "transfer", "fpl", "fantasy premier league",
}


def _tokenize(text: str) -> list[str]:
    return [tok for tok in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(tok) >= 2]


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(x.strip() for x in items if x and x.strip()))


def expand_focus_keywords(focus_query: str) -> list[str]:
    focus = (focus_query or "").strip().lower()
    if not focus:
        return []
    keywords = [focus]
    tokens = [t for t in _tokenize(focus) if t not in _STOPWORDS and len(t) >= 3]
    keywords.extend(tokens)
    if any(k in focus for k in ("premier league", "english premier league", "epl")):
        keywords.extend(sorted(_EPL_KEYWORDS))
    return _dedupe(keywords)


def focus_relevance_score(title: str, focus_query: str) -> float:
    title_l = (title or "").lower()
    if not title_l.strip() or not focus_query.strip():
        return 0.0

    keywords = expand_focus_keywords(focus_query)
    if not keywords:
        return 0.0

    token_hits = 0
    phrase_hits = 0
    title_tokens = set(_tokenize(title_l))

    for kw in keywords:
        if " " in kw:
            if kw in title_l:
                phrase_hits += 1
        elif kw in title_tokens:
            token_hits += 1

    score = (phrase_hits * 0.33) + (token_hits * 0.07)
    return max(0.0, min(1.0, round(score, 4)))


def is_low_signal_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    t_l = t.lower()
    words = _tokenize(t_l)
    hashtag_count = t_l.count("#")
    if len(words) < 2:
        return True
    if len(t_l) < 12:
        return True
    if t_l.startswith("#") and len(words) <= 3:
        return True
    if hashtag_count >= 3 and len(words) <= 5:
        return True
    noisy_markers = ("#shorts", "#oc", "relatablestories", "funnymemes")
    if any(m in t_l for m in noisy_markers) and (hashtag_count >= 2 or len(words) <= 12):
        return True
    alnum = sum(1 for ch in t if ch.isalnum())
    if alnum == 0:
        return True
    symbol_ratio = 1.0 - (alnum / max(len(t), 1))
    if symbol_ratio > 0.55:
        return True
    return False


def channel_profile_similarity(title: str, profile_text: str) -> float:
    a = {x for x in _tokenize(title) if x not in _STOPWORDS}
    b = {x for x in _tokenize(profile_text) if x not in _STOPWORDS}
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if overlap <= 0:
        return 0.0
    score = overlap / max(min(len(a), len(b)), 1)
    return max(0.0, min(1.0, round(score, 4)))
