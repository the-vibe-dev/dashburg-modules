from __future__ import annotations

from types import SimpleNamespace

from core import knowledge


class _FakeKnowledgeClient:
    def __init__(self) -> None:
        self.config = SimpleNamespace(min_confidence=0.7, min_usefulness=0.7)
        self.saved = []
        self.queries = []

    def add_record(self, payload):
        self.saved.append(payload)
        return {"ok": True, "record": payload}

    def search(self, query, *, filters=None, limit=10):
        self.queries.append({"query": query, "filters": filters or {}, "limit": limit})
        return [{"title": "Prior trend", "summary": "Use concise B2B framing"}]


def test_search_context_passes_domain(monkeypatch) -> None:
    client = _FakeKnowledgeClient()
    monkeypatch.setattr(knowledge, "get_knowledge_client", lambda: client)

    rows = knowledge.search_context("founder outreach", domain="trend_research", limit=3)

    assert rows[0]["title"] == "Prior trend"
    assert client.queries[0]["filters"]["domain"] == "trend_research"


def test_maybe_add_record_honors_quality_gate(monkeypatch) -> None:
    client = _FakeKnowledgeClient()
    monkeypatch.setattr(knowledge, "get_knowledge_client", lambda: client)

    skipped = knowledge.maybe_add_record(
        {"record_type": "trend_summary", "title": "Low quality", "summary": "skip", "content": "skip"},
        confidence=0.4,
        usefulness=0.6,
        reusable=True,
    )
    written = knowledge.maybe_add_record(
        {"record_type": "trend_summary", "title": "High quality", "summary": "keep", "content": "keep"},
        confidence=0.91,
        usefulness=0.86,
        reusable=True,
    )

    assert skipped["skipped"] is True
    assert written["ok"] is True
    assert len(client.saved) == 1


def test_format_context_outputs_compact_bullets() -> None:
    out = knowledge.format_context(
        [
            {"title": "Pattern A", "summary": "Short lesson"},
            {"title": "Pattern B", "summary": "Another lesson"},
        ]
    )

    assert "- Pattern A: Short lesson" in out
    assert "- Pattern B: Another lesson" in out
