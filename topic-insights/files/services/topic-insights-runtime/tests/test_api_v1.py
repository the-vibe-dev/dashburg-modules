from __future__ import annotations

import time
from datetime import datetime

from apps.api import api_v1


def test_trending_topics_endpoint_returns_list(monkeypatch):
    class _Pain:
        def __init__(self, topic):
            from datetime import datetime

            self.topic = topic
            self.created_at = datetime.utcnow()
            self.frustration_keywords = ["ghosting", "resume"]
            self.raw_post_id = None

    monkeypatch.setattr("apps.api.api_v1.list_pains", lambda topic=None, limit=2000: [_Pain("jobs"), _Pain("jobs")])
    data = api_v1.trending_topics(limit=20)
    assert isinstance(data.get("items"), list)
    assert data["items"][0]["topic"] == "jobs"


def test_targeted_run_returns_quickly(monkeypatch):
    def _slow(*args, **kwargs):
        time.sleep(1.5)
        return {"run_id": "pipeline-1", "ideas": 0}

    monkeypatch.setattr("apps.api.api_v1.run_end_to_end", _slow)

    start = time.time()
    out = api_v1.run_targeted(api_v1.TargetedRunIn(query="job ghosting", topic="jobs", limit=10, enable_youtube=False))
    elapsed = time.time() - start
    assert out.run_id
    assert out.status == "queued"
    assert elapsed < 1.0


def test_run_detail_prefers_run_scoped_outputs(monkeypatch):
    class _Row:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def model_dump(self):
            return dict(self.__dict__)

    class _Event:
        def __init__(self, stage_name: str, output_count: int):
            self.stage_name = stage_name
            self.output_count = output_count
            self.created_at = datetime.utcnow()

    monkeypatch.setattr("apps.api.api_v1.get_run_events_by_run_id", lambda run_id, limit=500: [_Event("ideas", 2)])
    monkeypatch.setattr("apps.api.api_v1.provider_stats_for_run", lambda run_id, limit=500: [])
    monkeypatch.setattr("apps.api.api_v1.list_clusters", lambda limit=20, run_id=None: [_Row(cluster_id="c-run", cluster_label="run cluster")] if run_id == "run-1" else [])
    monkeypatch.setattr("apps.api.api_v1.list_ideas", lambda cluster_id=None, limit=20, run_id=None: [_Row(idea_id="i-run", idea_name="run idea")] if run_id == "run-1" else [])
    monkeypatch.setattr("apps.api.api_v1.list_pains", lambda topic=None, limit=80, run_id=None: [_Row(pain_id="p-run", raw_post_id="", pain_summary="run pain")] if run_id == "run-1" else [])

    out = api_v1.run_detail("run-1")
    assert out["outputs"]["clusters"][0]["cluster_id"] == "c-run"
    assert out["outputs"]["ideas"][0]["idea_id"] == "i-run"
    assert out["outputs"]["top_pains"][0]["pain_id"] == "p-run"
