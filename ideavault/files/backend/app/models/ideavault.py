from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index
from sqlmodel import Field, SQLModel


class IdeaVaultItem(SQLModel, table=True):
    __tablename__ = "ideavault_items"

    id: str = Field(primary_key=True, max_length=64)
    title: str = Field(default="", max_length=500, index=True)
    summary: str = Field(default="")
    type: str = Field(default="idea", index=True, max_length=32)
    status: str = Field(default="new", index=True, max_length=32)
    tags_json: str = Field(default="[]")
    source_json: str = Field(default="{}")
    payload_json: str = Field(default="{}")
    score: float | None = Field(default=None, index=True)
    pinned: bool = Field(default=False, index=True)
    priority_rank: int | None = Field(default=None, index=True)
    deleted: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    last_touched_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class TopicFactoryQueueItem(SQLModel, table=True):
    __tablename__ = "topicfactory_queue"

    id: str = Field(primary_key=True, max_length=64)
    topic_text: str = Field(default="", index=True, max_length=500)
    source_json: str = Field(default="{}")
    ideavault_item_id: str | None = Field(default=None, index=True, max_length=64)
    status: str = Field(default="queued", index=True, max_length=32)
    run_id: str | None = Field(default=None, index=True, max_length=120)
    params_json: str = Field(default="{}")
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))


Index("ix_ideavault_status_created", IdeaVaultItem.status, IdeaVaultItem.created_at)
Index("ix_ideavault_priority_pinned", IdeaVaultItem.priority_rank, IdeaVaultItem.pinned)
Index("ix_queue_status_created", TopicFactoryQueueItem.status, TopicFactoryQueueItem.created_at)
