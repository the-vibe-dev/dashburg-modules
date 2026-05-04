from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    db_path: str
    schema_version: int = 1


class AppGenConfigResponse(BaseModel):
    appgen: dict[str, Any]


class PainExtractRequest(BaseModel):
    source_type: str = "all"
    limit: int = 200
    use_llm: bool = False


class PainPointCreateRequest(BaseModel):
    text: str
    severity: float | None = None
    category: str | None = None
    source_ref: str = "manual"


class GenerateRequest(BaseModel):
    pain_point_ids: list[str] = Field(default_factory=list)
    seed_text: str = ""
    count: int = 5
    constraints: dict[str, Any] = Field(default_factory=dict)


class IdeaUpdateRequest(BaseModel):
    title: str | None = None
    one_liner: str | None = None
    problem_statement: str | None = None
    target_user: str | None = None
    primary_pain_point: str | None = None
    category: str | None = None
    status: str | None = None
    execution_stage: str | None = None
    scores: dict[str, Any] | None = None
    tags: list[str] | None = None


class GenerateResponse(BaseModel):
    run_id: str
    idea_ids: list[str]


class ExportResponse(BaseModel):
    run_id: str
    file: str
    schema_version: int = 1


class StageResponse(BaseModel):
    run_id: str
    idea_id: str
    artifact_id: str
    provider: str
    model: str


class EventEnvelope(BaseModel):
    topic: str
    payload: dict[str, Any]


class MetricsSummaryResponse(BaseModel):
    ideas: int
    pain_points: int
    runs: int
    outbox_events: int
    total_cost_usd: float
    total_calls: int
    total_tokens: int
