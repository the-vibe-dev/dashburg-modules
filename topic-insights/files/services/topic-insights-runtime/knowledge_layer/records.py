from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any


MAIL_RECORD_TYPES = {
    "email_template",
    "email_playbook",
    "email_classification_rule",
    "reply_pattern",
    "followup_pattern",
    "outreach_strategy",
    "campaign_lesson",
    "lead_handling_rule",
    "inbox_triage_rule",
    "customer_response_pattern",
}

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def normalize_record_type(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return raw or "generic_note"


def normalize_tags(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        tag = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def redact_mail_content(text: str) -> str:
    out = _EMAIL_RE.sub("[redacted-email]", str(text or ""))
    out = _URL_RE.sub("[redacted-url]", out)
    out = _PHONE_RE.sub("[redacted-phone]", out)
    return out


def _normalized_record(payload: dict[str, Any]) -> dict[str, Any]:
    raw = deepcopy(payload)
    scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    relationships = raw.get("relationships") if isinstance(raw.get("relationships"), list) else []
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    title = str(raw.get("title") or "").strip()
    summary = str(raw.get("summary") or "").strip()
    content = str(raw.get("content") or "").strip()
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {"name": str(raw.get("source") or "").strip()}
    record = {
        "record_type": normalize_record_type(str(raw.get("record_type") or "")),
        "title": title,
        "summary": summary,
        "content": content,
        "tags": normalize_tags(raw.get("tags") if isinstance(raw.get("tags"), list) else []),
        "domain": str(raw.get("domain") or "").strip().lower() or "general",
        "topic": str(raw.get("topic") or "").strip(),
        "source": source,
        "scores": {str(key): value for key, value in scores.items()},
        "relationships": [row for row in relationships if isinstance(row, dict)],
        "visibility_scope": str(raw.get("visibility_scope") or "team").strip().lower() or "team",
        "status": str(raw.get("status") or "experimental").strip().lower() or "experimental",
        "metadata": metadata,
    }
    return record


def build_record(payload: dict[str, Any]) -> dict[str, Any]:
    record = _normalized_record(payload)
    if "idempotency_key" not in record["metadata"]:
        record["metadata"]["idempotency_key"] = record_fingerprint(record)
    return record


def validate_record(payload: dict[str, Any]) -> list[str]:
    row = build_record(payload)
    errors: list[str] = []
    if not row["record_type"]:
        errors.append("record_type is required")
    if not row["title"] and not row["summary"]:
        errors.append("title or summary is required")
    if not row["content"] and not row["summary"]:
        errors.append("content or summary is required")
    if not isinstance(row["source"], dict):
        errors.append("source must be an object")
    return errors


def record_fingerprint(payload: dict[str, Any]) -> str:
    row = _normalized_record(payload)
    fingerprint_source = {
        "record_type": row["record_type"],
        "title": row["title"].lower(),
        "summary": row["summary"].lower(),
        "content": row["content"].lower(),
        "tags": row["tags"],
        "domain": row["domain"],
        "topic": row["topic"].lower(),
        "status": row["status"],
    }
    packed = json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def should_write_record(
    *,
    confidence: float | None,
    usefulness: float | None,
    min_confidence: float,
    min_usefulness: float,
    reusable: bool = True,
) -> bool:
    if not reusable:
        return False
    c = float(confidence if confidence is not None else 0.0)
    u = float(usefulness if usefulness is not None else 0.0)
    return c >= min_confidence and u >= min_usefulness
