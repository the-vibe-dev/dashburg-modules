from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field, SQLModel


class WeeklyReview(SQLModel, table=True):
    __tablename__ = "weekly_reviews"

    id: str = Field(primary_key=True, max_length=64)
    week_start: str = Field(default="", index=True, max_length=32)
    week_end: str = Field(default="", index=True, max_length=32)
    status: str = Field(default="ready", index=True, max_length=32)
    generated_by: str = Field(default="system", max_length=64)
    dataset_json: str = Field(default="{}")
    analysis_json: str = Field(default="{}")
    analysis_model: str | None = Field(default=None, max_length=128)
    analysis_error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


Index("ix_weekly_reviews_week", WeeklyReview.week_start, WeeklyReview.week_end)
