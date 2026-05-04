from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentTemplateSummary(BaseModel):
    id: str
    name: str
    description: str
    category: str = "general"
    strict_by_default: bool = True


class AgentTemplateDetail(AgentTemplateSummary):
    version: str = "1.0.0"
    agent_type: str = "general"
    domain_focus: str = ""
    execution_mode: str = "task"
    runtime: str = "python"
    model_provider: str | None = None
    model_name: str | None = None
    recommended_skills: list[str] = Field(default_factory=list)
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    disallowed_capabilities: list[str] = Field(default_factory=list)
    default_prompts: dict[str, str] = Field(default_factory=dict)
    runtime_policies: dict[str, Any] = Field(default_factory=dict)
    execution_expectations: list[str] = Field(default_factory=list)
    ui_hints: dict[str, Any] = Field(default_factory=dict)
