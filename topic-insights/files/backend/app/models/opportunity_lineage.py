from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class OpportunityLineage(SQLModel, table=True):
    __tablename__ = "opportunity_lineage"

    id: str = Field(primary_key=True, index=True)
    from_kind: str = Field(default="", index=True)
    from_id: str = Field(default="", index=True)
    to_kind: str = Field(default="", index=True)
    to_id: str = Field(default="", index=True)
    relation: str = Field(default="derived", index=True)

    context_json: str = Field(default="{}")
    score: float | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
