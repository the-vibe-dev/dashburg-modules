from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrendsRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    sources: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    subreddits: list[str] = Field(default_factory=list)
    region: str = "US"
    query: str | None = None
    objective: str = "video_blog_app_ideas"
    use_openai_strategy: bool = True
    llm_rerank_top_n: int = Field(default=50, ge=0, le=100)
    min_focus_relevance: float = Field(default=0.2, ge=0.0, le=1.0)


class TopicActionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    note: str | None = None


class TrendsExportRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: str = "topic_factory_v1"
    topic_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    include_actions: bool = True


class TopicFactoryImportRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    exported_payload: dict[str, Any]
