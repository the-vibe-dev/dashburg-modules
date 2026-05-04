from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PromotedIdeaCreate(BaseModel):
    run_id: str
    idea_id: str
    raw_json: dict[str, Any]


class PromotedIdeaRead(BaseModel):
    id: int
    source_run_id: str
    source_idea_id: str
    title: str
    summary: str
    idea_type: str = "app"
    problem_summary: str = ""
    target_user: str = ""
    why_now: str = ""
    first_build_step: str = ""
    raw_json: dict[str, Any]
    created_at: datetime


class WeeklyReviewRead(BaseModel):
    id: str
    week_start: str
    week_end: str
    status: str
    generated_by: str
    dataset: dict[str, Any]
    analysis: dict[str, Any]
    analysis_model: str | None = None
    analysis_error: str | None = None
    created_at: datetime
    updated_at: datetime
