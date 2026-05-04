from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

from trend_harvester.enums import TopicAction


YOUTUBE_CATEGORY_MAP = {
    "Film & Animation": "1",
    "Autos & Vehicles": "2",
    "Music": "10",
    "Pets & Animals": "15",
    "News & Politics": "25",
    "Howto & Style": "26",
    "Education": "27",
    "Science & Technology": "28",
    "Entertainment": "24",
    "Sports": "17",
    "Travel & Events": "19",
    "People & Blogs": "22",
    "Comedy": "23",
    "Nonprofits & Activism": "29",
    "Gaming": "20",
}


class SourceConfig(BaseModel):
    enabled: bool = True
    limit: int | None = None


class SourcesPayload(BaseModel):
    youtube: SourceConfig = Field(default_factory=SourceConfig)
    trends: SourceConfig = Field(default_factory=SourceConfig)
    reddit: SourceConfig = Field(default_factory=SourceConfig)
    x: SourceConfig = Field(default_factory=SourceConfig)


class LimitsPayload(BaseModel):
    size: Literal["small", "medium", "large"] = "small"
    youtube: int | None = None
    reddit: int | None = None
    trends: int | None = None
    x: int | None = None


class RunStartRequest(BaseModel):
    sources: SourcesPayload = Field(default_factory=SourcesPayload)
    limits: LimitsPayload = Field(default_factory=LimitsPayload)
    categories: list[str] = Field(
        default_factory=lambda: ["News & Politics", "Entertainment", "Sports", "Gaming", "Science & Technology"]
    )
    subreddits: list[str] = Field(default_factory=lambda: ["technology", "worldnews", "todayilearned", "science", "futurology", "AskReddit", "gaming", "news"])
    region: str = "US"
    focus_query: str = Field(default="", validation_alias=AliasChoices("focus_query", "query", "topic", "trend_query", "niche", "prompt"))
    objective: str = "video_blog_app_ideas"
    use_openai_strategy: bool = True
    llm_rerank_top_n: int = Field(default=50, ge=0, le=100)
    min_focus_relevance: float = Field(default=0.12, ge=0.0, le=1.0)

    @field_validator("subreddits")
    @classmethod
    def max_subreddits(cls, value: list[str]) -> list[str]:
        if len(value) > 20:
            raise ValueError("subreddits length must be <= 20")
        return value


class RunStartResponse(BaseModel):
    run_id: str


class RunResponse(BaseModel):
    id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    params_json: dict
    totals_json: dict
    error: str | None


class RunLogsResponse(BaseModel):
    run_id: str
    offset: int
    next_offset: int
    total_lines: int
    has_more: bool
    lines: list[str] = Field(default_factory=list)


class TopicResult(BaseModel):
    topic_id: str
    title: str
    score: float
    sources: list[str]
    summary: str
    hooks: list[str]
    channels: dict[str, float]
    channel_scores: dict[str, float] = Field(default_factory=dict)
    channel_reasons: dict[str, list[dict]] = Field(default_factory=dict)
    channel_rankings: list[dict] = Field(default_factory=list)
    ranking_debug: dict[str, dict] = Field(default_factory=dict)


class RunResultsResponse(BaseModel):
    run_id: str
    status: str
    top_overall: list[TopicResult]
    top_per_channel: dict[str, list[TopicResult]]
    channel_fit_counts: dict[str, int]
    top_by_source: dict[str, list[TopicResult]] = Field(default_factory=dict)
    channels_used: list[dict] = Field(default_factory=list)
    empty_channels: list[str] = Field(default_factory=list)
    fetch_plan: dict = Field(default_factory=dict)
    idea_candidates: list[dict] = Field(default_factory=list)
    idea_candidates_by_type: dict[str, list[dict]] = Field(default_factory=dict)
    idea_groups: list[dict] = Field(default_factory=list)
    big_calls: list[dict] = Field(default_factory=list)
    score_breakdowns: dict[str, dict] = Field(default_factory=dict)
    evidence_links: dict[str, list[dict]] = Field(default_factory=dict)
    recommended_next_actions: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    strategy_status: dict = Field(default_factory=dict)


class TopicDetailResponse(BaseModel):
    topic_id: str
    title: str
    summary: str
    hooks: list[str]
    sources: list[dict]
    metrics: dict
    channel_relevance: dict[str, float]
    latest_action: str | None
    notes: list[str]


class TopicActionRequest(BaseModel):
    action: TopicAction
    note: str | None = Field(default=None, max_length=500)


class GenericStatusResponse(BaseModel):
    status: str


class ActionsResponse(BaseModel):
    items: list[dict]


class ExportRequest(BaseModel):
    topic_ids: list[str] = Field(min_length=1, max_length=200)
    format: Literal["topic_factory_v1", "idea_factory_v2", "topic_factory_v2"] = "topic_factory_v1"
    run_id: str | None = None
    include_actions: bool = False


class ExportResponse(BaseModel):
    topics: list[dict] = Field(default_factory=list)
    ideas: list[dict] = Field(default_factory=list)
    idea_groups: list[dict] = Field(default_factory=list)
    big_calls: list[dict] = Field(default_factory=list)
    score_breakdowns: dict[str, dict] = Field(default_factory=dict)
    evidence_links: dict[str, list[dict]] = Field(default_factory=dict)
    recommended_next_actions: list[str] = Field(default_factory=list)


class ConfigValidateResponse(BaseModel):
    valid: bool
    missing: list[str]


class OpenAiApiKeyStatus(BaseModel):
    configured: bool
    source: str
    masked: str
