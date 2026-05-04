from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicProxyErrorResponse(BaseModel):
    message: str
    upstream_status: int | None = None
    upstream_body: Any | None = None


class TargetedRunRequest(BaseModel):
    query: str
    topic: str
    limit: int = Field(default=20, ge=1, le=100)
    enable_youtube: bool = False
    youtube: bool | None = None
    target_final_ideas: int = Field(default=5, ge=1, le=100)
    ingest_overrides: dict[str, Any] | None = None
    max_comment_posts: int | None = Field(default=None, ge=1, le=50)
    max_comments_per_thread: int | None = Field(default=50, ge=1, le=200)
    recency_window: str | None = Field(default="30d")
    subreddits: list[str] | None = None
    search_terms: list[str] | None = None
    use_default_subreddits: bool = True
    use_default_search_terms: bool = True
    enable_reddit: bool = True
    enable_web_search: bool = True
    low_fanout_mode: bool = False
    category_mode: str = Field(default="broad")
    category_filters: list[str] | None = None
    exclude_categories: list[str] | None = None


class AutoRunRequest(BaseModel):
    ideas_per_run: int = Field(default=5, ge=1, le=10)
    target_topics: int = Field(default=8, ge=1, le=25)
    limit_per_topic: int = Field(default=20, ge=1, le=100)
    enable_youtube: bool = False
    target_final_ideas: int | None = Field(default=None, ge=1, le=100)
    ingest_overrides: dict[str, Any] | None = None
    max_posts_per_source: int | None = Field(default=None, ge=1, le=100)
    max_comment_posts: int | None = Field(default=None, ge=1, le=50)
    max_comments_per_thread: int | None = Field(default=None, ge=1, le=200)
    recency_window: str | None = Field(default="30d")
    provider_order: list[str] | None = None
    safe_mode: bool = True
    concurrency: int | None = Field(default=None, ge=1, le=4)
    subreddits: list[str] | None = None
    search_terms: list[str] | None = None
    use_default_subreddits: bool = True
    use_default_search_terms: bool = True
    enable_reddit: bool = True
    enable_web_search: bool = True
    low_fanout_mode: bool = False
    category_mode: str = Field(default="broad")
    category_filters: list[str] | None = None
    exclude_categories: list[str] | None = None


class StartRunRequest(BaseModel):
    query: str
    topic: str
    limit: int = Field(default=200, ge=1, le=1000)
    enable_youtube: bool = False
    target_final_ideas: int = Field(default=20, ge=1, le=200)
    enable_pain_graph: bool = True
    ingest_overrides: dict[str, Any] | None = None
    subreddits: list[str] | None = None
    search_terms: list[str] | None = None
    use_default_subreddits: bool = True
    use_default_search_terms: bool = True
    enable_reddit: bool = True
    enable_web_search: bool = True
    low_fanout_mode: bool = False
    category_mode: str = Field(default="broad")
    category_filters: list[str] | None = None
    exclude_categories: list[str] | None = None


class PromoteIdeaRequest(BaseModel):
    run_id: str | None = None
    idea_id: str | None = None
    title: str
    summary: str | None = None
    score: float | None = None
    tags: list[str] = Field(default_factory=list)
    raw_json: dict[str, Any] = Field(default_factory=dict)
