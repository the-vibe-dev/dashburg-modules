from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import KnowledgeConfig
from .records import MAIL_RECORD_TYPES, build_record, redact_mail_content, validate_record


class KnowledgeClient:
    def __init__(self, config: KnowledgeConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
            headers["X-API-Key"] = self.config.api_token
        return headers

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
        if not self.config.enabled:
            return {"ok": False, "skipped": True, "reason": "knowledge_disabled"}
        encoded_query = urllib.parse.urlencode({key: value for key, value in (query or {}).items() if value is not None})
        url = f"{self.config.api_url}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url=url, method=method.upper(), data=data, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except Exception:
                parsed = {"detail": body}
            if self.config.fail_hard:
                raise
            return {"ok": False, "status": exc.code, "error": parsed}
        except Exception as exc:
            if self.config.fail_hard:
                raise
            return {"ok": False, "error": str(exc)}

    def _spool(self, action: str, payload: dict[str, Any]) -> None:
        if not self.config.spool_enabled:
            return
        line = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "payload": payload,
        }
        with self.config.spool_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=True) + "\n")

    def add_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not (self.config.enabled and self.config.write_enabled):
            return {"ok": True, "skipped": True, "reason": "write_disabled"}
        errors = validate_record(payload)
        if errors:
            return {"ok": False, "skipped": True, "reason": "invalid_record", "errors": errors}
        record = build_record(payload)
        response = self._request("POST", "/records", payload={"record": record})
        if not response or response.get("ok") is False:
            self._spool("add_record", {"record": record})
        return response if isinstance(response, dict) else {"ok": True, "result": response}

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not (self.config.enabled and self.config.read_enabled):
            return []
        response = self._request("POST", "/search", payload={"query": query, "filters": filters or {}, "limit": limit})
        if isinstance(response, dict):
            rows = response.get("items") if isinstance(response.get("items"), list) else response.get("results")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def similar(
        self,
        *,
        record_id: str | None = None,
        text: str | None = None,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not (self.config.enabled and self.config.read_enabled):
            return []
        response = self._request("POST", "/similar", payload={"record_id": record_id, "text": text, "filters": filters or {}, "limit": limit})
        if isinstance(response, dict):
            rows = response.get("items") if isinstance(response.get("items"), list) else response.get("results")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def top(self, *, domain: str | None = None, topic: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not (self.config.enabled and self.config.read_enabled):
            return []
        response = self._request("GET", "/top", query={"domain": domain, "topic": topic, "limit": limit})
        if isinstance(response, dict):
            rows = response.get("items") if isinstance(response.get("items"), list) else response.get("results")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not (self.config.enabled and self.config.read_enabled):
            return {"ok": True, "skipped": True, "reason": "read_disabled"}
        response = self._request("POST", "/evaluate", payload=payload)
        return response if isinstance(response, dict) else {"ok": True, "result": response}

    def supersede(self, record_id: str, superseded_by: str, *, note: str = "") -> dict[str, Any]:
        if not (self.config.enabled and self.config.write_enabled):
            return {"ok": True, "skipped": True, "reason": "write_disabled"}
        response = self._request("POST", "/supersede", payload={"record_id": record_id, "superseded_by": superseded_by, "note": note})
        return response if isinstance(response, dict) else {"ok": True, "result": response}

    def add_email_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = build_record({"record_type": "email_template", **payload})
        return self.add_record(row)

    def add_reply_pattern(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = build_record({"record_type": "reply_pattern", **payload})
        return self.add_record(row)

    def add_outreach_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = build_record({"record_type": "outreach_strategy", **payload})
        return self.add_record(row)

    def search_mail_knowledge(self, query: str, *, filters: dict[str, Any] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        merged = dict(filters or {})
        merged["record_types"] = sorted(MAIL_RECORD_TYPES)
        return self.search(query, filters=merged, limit=limit)

    def add_mail_record(
        self,
        *,
        record_type: str,
        title: str,
        summary: str,
        content: str,
        tags: list[str] | None = None,
        topic: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_content = redact_mail_content(content) if self.config.mail_redaction_enabled else content
        normalized_summary = redact_mail_content(summary) if self.config.mail_redaction_enabled else summary
        return self.add_record(
            {
                "record_type": record_type,
                "title": title,
                "summary": normalized_summary,
                "content": normalized_content,
                "tags": tags or [],
                "domain": "mail",
                "topic": topic,
                "source": {"name": "dashburg_mail"},
                "status": "verified",
                "metadata": metadata or {},
            }
        )
