from __future__ import annotations

from core.discovery import discover_topics


def test_discover_topics_falls_back_without_llm(monkeypatch):
    class _Post:
        def __init__(self, text):
            self.text = text

    monkeypatch.setattr("core.discovery.reddit_search", lambda q, limit=20: [_Post("job application ghosting no feedback")])
    monkeypatch.setattr("core.discovery.web_search", lambda q, limit=15: [_Post("adhd executive dysfunction shame underachievement")])
    monkeypatch.setattr("core.discovery.chat_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("llm down")))

    topics = discover_topics(target=5)
    assert topics
    assert len(topics) <= 5
