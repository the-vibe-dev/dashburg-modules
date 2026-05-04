from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentBase(BaseModel):
    name: str
    slug: str
    description: str = ""
    agent_type: str = "general"
    runtime: str = "python"
    model_provider: str | None = None
    model_name: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)
    env_config: dict[str, str] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)
    network_access: bool = False
    sandbox_mode: str = "workspace-write"
    yolo_mode: bool = False
    template_id: str | None = None
    specialization_mode: str = "strict"
    role_identity: str | None = None
    domain_focus: str | None = None
    execution_mode: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    runtime_policies: dict[str, Any] = Field(default_factory=dict)
    saved_prompts: dict[str, str] = Field(default_factory=dict)
    specialization_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCreate(AgentBase):
    workspace_path: str | None = None
    selected_skills: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_type: str | None = None
    runtime: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_settings: dict[str, Any] | None = None
    env_config: dict[str, str] | None = None
    flags: dict[str, Any] | None = None
    network_access: bool | None = None
    sandbox_mode: str | None = None
    yolo_mode: bool | None = None
    template_id: str | None = None
    specialization_mode: str | None = None
    role_identity: str | None = None
    domain_focus: str | None = None
    execution_mode: str | None = None
    allowed_tools: list[str] | None = None
    runtime_policies: dict[str, Any] | None = None
    saved_prompts: dict[str, str] | None = None
    specialization_metadata: dict[str, Any] | None = None


class AgentOut(AgentBase):
    id: str
    workspace_path: str
    selected_skills: list[str] = Field(default_factory=list)
    status: str = "created"
    last_run_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentStatus(BaseModel):
    agent_id: str
    status: str
    pid: int | None = None
    active_run_id: str | None = None
    last_run_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime


class AgentRunRequest(BaseModel):
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    mailbox_poll_seconds: int | None = None


class AgentMailboxMessageCreate(BaseModel):
    sender: str = "dashburg"
    subject: str = ""
    body: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDispatchRequest(BaseModel):
    sender: str = "dashburg"
    subject: str = "Dispatch Task"
    instruction: str
    command: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True


class AgentActionResponse(BaseModel):
    agent_id: str
    action: str
    status: str
    message: str
    run_id: str | None = None
