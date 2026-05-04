from __future__ import annotations

import pytest

from trend_harvester.services.llm import LLMAnalyzer


def test_parse_json_object_from_plain_json():
    parsed = LLMAnalyzer._parse_json_object_from_text('{"summary":"ok","hooks":[],"channel_relevance":{}}')
    assert parsed["summary"] == "ok"


def test_parse_json_object_with_think_wrapper():
    raw = '<think>hidden reasoning</think>{"summary":"ok","hooks":[],"channel_relevance":{}}'
    parsed = LLMAnalyzer._parse_json_object_from_text(raw)
    assert parsed["summary"] == "ok"


def test_parse_json_object_with_markdown_fence():
    raw = "```json\n{\"summary\":\"ok\",\"hooks\":[],\"channel_relevance\":{}}\n```"
    parsed = LLMAnalyzer._parse_json_object_from_text(raw)
    assert parsed["summary"] == "ok"


def test_parse_json_object_extracted_from_prose():
    raw = 'Sure, here is the result: {"summary":"ok","hooks":[],"channel_relevance":{}} Thanks.'
    parsed = LLMAnalyzer._parse_json_object_from_text(raw)
    assert parsed["summary"] == "ok"


def test_parse_json_object_empty_raises():
    with pytest.raises(ValueError):
        LLMAnalyzer._parse_json_object_from_text("")
