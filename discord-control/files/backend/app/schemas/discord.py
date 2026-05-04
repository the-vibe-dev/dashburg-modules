from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DiscordIntegrationSettingsUpdate(BaseModel):
    enabled: bool | None = None

    bridge_url: str | None = None
    bridge_auth_enabled: bool | None = None
    bridge_api_key: str | None = None
    bot_token: str | None = None
    guild_sync_mode: str | None = None
    heartbeat_poll_seconds: int | None = Field(default=None, ge=5, le=3600)

    allowed_user_ids: list[str] | None = None
    allowed_guild_ids: list[str] | None = None
    allowed_channel_ids: list[str] | None = None
    allowed_role_ids: list[str] | None = None
    allowed_approver_ids: list[str] | None = None

    dm_disabled: bool | None = None
    read_only_mode: bool | None = None
    dispatch_enabled: bool | None = None
    require_explicit_approval: bool | None = None
    direct_qwen_fallback_enabled: bool | None = None
    policy_deterministic_enabled: bool | None = None
    llm_reviewer_enabled: bool | None = None
    llm_reviewer_model: str | None = None
    isolated_execution_required_for_risky: bool | None = None
    direct_execution_disabled: bool | None = None
    raw_shell_disabled: bool | None = None

    session_provider: str | None = None
    default_model: str | None = None
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_context_budget: int | None = Field(default=None, ge=256, le=128000)
    session_ttl_seconds: int | None = Field(default=None, ge=300, le=604800)
    future_tool_use_enabled: bool | None = None
    orchestration_first_routing: bool | None = None

    memory_source_primary: str | None = None
    memory_source_fallback: str | None = None
    memory_append_enabled: bool | None = None
    memory_append_mode: str | None = None
    memory_write_guardrails: bool | None = None
    memory_relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class DiscordConnectivityTestRequest(BaseModel):
    include_bridge: bool = True
    include_redis: bool = True
    include_memory: bool = True


class DiscordSessionBootstrapRequest(BaseModel):
    user_id: str = Field(min_length=1)
    guild_id: str = ""
    channel_id: str = ""
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscordMemoryReindexRequest(BaseModel):
    dry_run: bool = False


class DiscordMemoryAppendRequest(BaseModel):
    note: str = Field(min_length=8)
    kind: str = "operational_note"
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    dry_run: bool = True


class DiscordDispatchRequestIngest(BaseModel):
    command: str = ""
    action_type: str = ""
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    requester: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscordApprovalDecisionRequest(BaseModel):
    dispatch_request_id: str = Field(min_length=8)
    approver_user_id: str = Field(min_length=1)
    reason: str = ""
    replay_token: str = Field(min_length=8)


class DiscordSessionResolveRequest(BaseModel):
    user_id: str = Field(min_length=1)
    guild_id: str = ""
    channel_id: str = ""


class DiscordPolicyEvaluateRequest(BaseModel):
    action_type: str = Field(min_length=1)
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    requester: dict[str, Any] = Field(default_factory=dict)


class DispatchWorkerRegisterRequest(BaseModel):
    worker_id: str = Field(min_length=2)
    label: str = ""
    host: str = ""
    capabilities: list[str] = Field(default_factory=list)
    supports_isolated_execution: bool = False
    dispatch_enabled: bool = True
    auth_key_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchWorkerHeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=2)
    status: str = "online"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchWorkerPollRequest(BaseModel):
    worker_id: str = Field(min_length=2)
    capabilities: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=50)


class DispatchWorkerResultRequest(BaseModel):
    worker_id: str = Field(min_length=2)
    status: str = Field(min_length=2)
    result_summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
