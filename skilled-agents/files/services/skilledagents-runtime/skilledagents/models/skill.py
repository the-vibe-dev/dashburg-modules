from __future__ import annotations

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    id: str
    slug: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    path: str
    checksum: str | None = None


class SkillDetail(SkillSummary):
    readme: str | None = None
    metadata: dict = Field(default_factory=dict)


class SkillCreate(BaseModel):
    id: str
    name: str | None = None
    description: str = ""
    category: str = "custom"
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0.0"
    readme: str | None = None
