from __future__ import annotations
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, JSON

class RawPost(SQLModel, table=True):
    id: str = Field(primary_key=True)
    run_id: Optional[str] = Field(default=None, index=True)
    source: str = Field(index=True)
    url: str
    author: Optional[str] = None
    timestamp: datetime = Field(index=True)
    text: str
    engagement_score: int = 0
    metadata_: dict = Field(default_factory=dict, sa_column=Column("metadata", JSON))

class ExtractedPain(SQLModel, table=True):
    pain_id: str = Field(primary_key=True)
    run_id: Optional[str] = Field(default=None, index=True)
    raw_post_id: str = Field(index=True)
    topic: str = Field(index=True)
    pain_summary: str
    emotional_intensity: float
    frustration_keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    workaround_detected: bool = False
    workaround_type: Optional[str] = None
    existing_solution_mentions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    urgency_signal: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class PainCluster(SQLModel, table=True):
    cluster_id: str = Field(primary_key=True)
    run_id: Optional[str] = Field(default=None, index=True)
    cluster_label: str = Field(index=True)
    pain_count: int
    avg_intensity: float
    avg_engagement: float
    top_sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    competition_signal: float = 0.0
    monetization_signal: float = 0.0
    simplicity_score: float = 0.0
    pain_score: float = 0.0
    competition_penalty: float = 0.0
    opportunity_score: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class Idea(SQLModel, table=True):
    idea_id: str = Field(primary_key=True)
    run_id: Optional[str] = Field(default=None, index=True)
    cluster_id: str = Field(index=True)
    idea_name: str
    core_problem: str
    solution_summary: str
    mvp_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    estimated_build_time_days: int
    complexity_score: float
    competition_score: float
    monetization_score: float
    opportunity_score: float
    # Added in v3: evaluation & go-to-market signals
    demand_score: float = 0.0
    demand_summary: dict = Field(default_factory=dict, sa_column=Column(JSON))
    pricing_model: dict = Field(default_factory=dict, sa_column=Column(JSON))
    ctr_prediction: float = 0.0  # 0..1 estimate
    would_build_confidence: float = 0.0  # 0..1
    evaluation: dict = Field(default_factory=dict, sa_column=Column(JSON))
    competitor_apps: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class RunEvent(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    stage_name: str = Field(index=True)
    status: str = Field(index=True)
    input_count: int = 0
    output_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ApiCallLog(SQLModel, table=True):
    call_id: str = Field(primary_key=True)
    run_id: Optional[str] = Field(default=None, index=True)
    provider: str = Field(index=True)
    operation: str = Field(index=True)
    success: bool = True
    status_code: Optional[int] = None
    retries: int = 0
    latency_ms: float = 0.0
    cache_hit: bool = False
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_est: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
