from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel


class WebAgentRun(SQLModel, table=True):
    __tablename__ = "webagent_runs"

    id: str = Field(primary_key=True, max_length=64)
    target_url: str = Field(max_length=1200)
    run_type: str = Field(max_length=80)
    node_id: str = Field(default="", max_length=120)
    remote_job_id: str = Field(default="", index=True, max_length=64)
    status: str = Field(default="queued", index=True, max_length=40)
    settings_json: str = Field(default="{}")
    summary_json: str = Field(default="{}")
    artifact_manifest_json: str = Field(default="[]")
    result_json: str = Field(default="{}")
    error_message: str = Field(default="")
    notes: str = Field(default="")
    created_by: str = Field(default="ui", max_length=100)
    is_saved: bool = Field(default=False)
    is_useful: bool = Field(default=False)
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class WebAgentReport(SQLModel, table=True):
    __tablename__ = "webagent_reports"

    id: str = Field(primary_key=True, max_length=64)
    run_id: str = Field(index=True, max_length=64)
    title: str = Field(default="", max_length=240)
    summary_markdown: str = Field(default="")
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
