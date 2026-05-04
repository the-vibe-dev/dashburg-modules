from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel


class PromotedIdea(SQLModel, table=True):
    __tablename__ = "promoted_idea"

    id: int | None = Field(default=None, primary_key=True)
    source_run_id: str = Field(index=True, max_length=255)
    source_idea_id: str = Field(index=True, max_length=255)
    title: str = Field(default="Untitled idea", max_length=300)
    summary: str = Field(default="", max_length=4000)
    idea_type: str = Field(default="app", index=True, max_length=32)
    problem_summary: str = Field(default="", max_length=4000)
    target_user: str = Field(default="", max_length=1000)
    why_now: str = Field(default="", max_length=4000)
    first_build_step: str = Field(default="", max_length=4000)
    raw_json: str = Field(default="{}")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )
