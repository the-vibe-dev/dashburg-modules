from __future__ import annotations

import re


def normalize_topic_key(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"(^|\s)#", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

