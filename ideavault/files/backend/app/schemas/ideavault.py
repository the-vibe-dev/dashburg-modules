from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IdeaVaultCreate(BaseModel):
    title: str
    summary: str | None = ""
    type: str = "idea"
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    pinned: bool = False


class IdeaVaultPatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    source: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    score: float | None = None
    pinned: bool | None = None
    priority_rank: int | None = None


class IdeaVaultReorderRequest(BaseModel):
    orderedIds: list[str] = Field(default_factory=list)


class IdeaVaultRead(BaseModel):
    id: str
    title: str
    summary: str
    type: str
    status: str
    tags: list[str]
    source: dict[str, Any]
    payload: dict[str, Any]
    score: float | None
    pinned: bool
    priority_rank: int | None
    created_at: datetime
    updated_at: datetime
    last_touched_at: datetime
    queue_entry_id: str | None = None
    queue_status: str | None = None
    next_actions: list[dict[str, Any]] = Field(default_factory=list)


class TopicFactoryQueueCreate(BaseModel):
    topic_text: str
    source: dict[str, Any] = Field(default_factory=dict)
    ideavault_item_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class TopicFactoryQueuePatch(BaseModel):
    status: str | None = None


class TopicFactoryQueueRead(BaseModel):
    id: str
    topic_text: str
    source: dict[str, Any]
    ideavault_item_id: str | None
    status: str
    run_id: str | None
    params: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IdeaVaultImportFromSource(BaseModel):
    items: list[IdeaVaultCreate]
