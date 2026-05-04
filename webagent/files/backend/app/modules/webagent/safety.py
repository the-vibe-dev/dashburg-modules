from __future__ import annotations

from typing import Any

from app.modules.webagent.constants import DESTRUCTIVE_KEYWORDS


def detect_destructive_action(*, label: str | None = None, text: str | None = None, selector: str | None = None) -> dict[str, Any]:
    merged = " ".join([str(label or ""), str(text or ""), str(selector or "")]).strip().lower()
    hits = [kw for kw in DESTRUCTIVE_KEYWORDS if kw in merged]
    return {
        "is_destructive": bool(hits),
        "keywords": hits,
        "source": merged[:300],
    }


def mask_pii(value: str) -> str:
    text = str(value or "")
    if "@" in text and len(text) > 5:
        left, _, right = text.partition("@")
        if len(left) > 2:
            return f"{left[:2]}***@{right}"
    digits = [c for c in text if c.isdigit()]
    if len(digits) >= 7:
        return "***PII***"
    return text


def scrub_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in (payload or {}).items():
        low = str(key).lower()
        if any(token in low for token in ("token", "secret", "password", "api_key", "authorization")):
            out[key] = "***REDACTED***"
            continue
        if isinstance(val, str):
            out[key] = mask_pii(val)
        else:
            out[key] = val
    return out
