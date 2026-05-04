from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, DateTime, Field, SQLModel


class DiscordIntegrationSettings(SQLModel, table=True):
    __tablename__ = "discord_integration_settings"

    id: int | None = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)

    bridge_url: str = Field(default="http://127.0.0.1:8799", max_length=400)
    bridge_auth_enabled: bool = Field(default=True)
    bridge_api_key: str = Field(default="", max_length=255)
    bot_token: str = Field(default="", max_length=255)
    guild_sync_mode: str = Field(default="allowlist_only", max_length=64)
    heartbeat_poll_seconds: int = Field(default=30)

    allowed_user_ids_json: str = Field(default="[]")
    allowed_guild_ids_json: str = Field(default="[]")
    allowed_channel_ids_json: str = Field(default="[]")
    allowed_role_ids_json: str = Field(default="[]")
    allowed_approver_ids_json: str = Field(default="[]")

    dm_disabled: bool = Field(default=True)
    read_only_mode: bool = Field(default=True)
    dispatch_enabled: bool = Field(default=False)
    require_explicit_approval: bool = Field(default=True)
    direct_qwen_fallback_enabled: bool = Field(default=False)

    # Phase 2 policy safety defaults
    policy_deterministic_enabled: bool = Field(default=True)
    llm_reviewer_enabled: bool = Field(default=False)
    llm_reviewer_model: str = Field(default="qwen3:14b", max_length=120)
    isolated_execution_required_for_risky: bool = Field(default=True)
    direct_execution_disabled: bool = Field(default=True)
    raw_shell_disabled: bool = Field(default=True)

    session_provider: str = Field(default="redis", max_length=64)
    default_model: str = Field(default="qwen3:14b", max_length=120)
    default_temperature: float = Field(default=0.2)
    max_context_budget: int = Field(default=6000)
    session_ttl_seconds: int = Field(default=43200)
    future_tool_use_enabled: bool = Field(default=False)
    orchestration_first_routing: bool = Field(default=True)

    memory_source_primary: str = Field(default="/srv/dashburg/shared/MEM.md", max_length=400)
    memory_source_fallback: str = Field(default="~/MEM.md", max_length=400)
    memory_append_enabled: bool = Field(default=True)
    memory_append_mode: str = Field(default="significant_only", max_length=80)
    memory_write_guardrails: bool = Field(default=True)
    memory_relevance_threshold: float = Field(default=0.75)

    last_indexed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    last_append_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    last_heartbeat_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    last_seen_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    last_error: str = Field(default="")
    last_status_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class DiscordDispatchRequest(SQLModel, table=True):
    __tablename__ = "discord_dispatch_requests"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    status: str = Field(default="received", index=True, max_length=40)
    action_type: str = Field(index=True, max_length=120)
    target: str = Field(default="", index=True, max_length=200)
    arguments_json: str = Field(default="{}")
    normalized_json: str = Field(default="{}")

    requester_user_id: str = Field(default="", index=True, max_length=80)
    requester_guild_id: str = Field(default="", max_length=80)
    requester_channel_id: str = Field(default="", max_length=80)
    requester_role_ids_json: str = Field(default="[]")
    requester_name: str = Field(default="", max_length=160)

    source: str = Field(default="discord", index=True, max_length=40)
    source_command: str = Field(default="", max_length=200)
    prompt_summary: str = Field(default="")

    session_key: str = Field(default="", index=True, max_length=220)
    policy_decision: str = Field(default="deny", max_length=40)
    policy_reason: str = Field(default="")
    risk_level: str = Field(default="high", max_length=40)
    approval_required: bool = Field(default=True)
    isolated_required: bool = Field(default=False)

    dispatch_target_id: str = Field(default="", max_length=120)
    dispatch_worker_id: str = Field(default="", max_length=120)
    dispatch_job_ref: str = Field(default="", max_length=120)

    result_json: str = Field(default="{}")
    error: str = Field(default="")

    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))


class DiscordApprovalRequest(SQLModel, table=True):
    __tablename__ = "discord_approval_requests"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    dispatch_request_id: str = Field(index=True, max_length=64)
    status: str = Field(default="pending", index=True, max_length=30)
    approver_user_id: str = Field(default="", max_length=80)
    decision_reason: str = Field(default="")
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    replay_token_hash: str = Field(default="", max_length=140)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    decided_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))


class DiscordPolicyDecision(SQLModel, table=True):
    __tablename__ = "discord_policy_decisions"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    dispatch_request_id: str = Field(index=True, max_length=64)
    decision: str = Field(default="deny", max_length=40)
    risk_level: str = Field(default="high", max_length=40)
    requires_approval: bool = Field(default=True)
    downgraded_action_type: str = Field(default="", max_length=120)
    isolated_required: bool = Field(default=False)
    reasons_json: str = Field(default="[]")
    input_snapshot_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class DiscordRiskReview(SQLModel, table=True):
    __tablename__ = "discord_risk_reviews"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    dispatch_request_id: str = Field(index=True, max_length=64)
    reviewer: str = Field(default="heuristic", max_length=80)
    model: str = Field(default="", max_length=120)
    available: bool = Field(default=False)
    risk_level: str = Field(default="unknown", max_length=40)
    recommendation: str = Field(default="none", max_length=40)
    confidence: float = Field(default=0.0)
    intent_summary: str = Field(default="")
    suspicious_indicators_json: str = Field(default="[]")
    explanation: str = Field(default="")
    raw_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class DiscordAuditEvent(SQLModel, table=True):
    __tablename__ = "discord_audit_events"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    dispatch_request_id: str = Field(default="", index=True, max_length=64)
    event_type: str = Field(index=True, max_length=80)
    actor: str = Field(default="system", max_length=80)
    message: str = Field(default="")
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class DispatchWorkerHeartbeat(SQLModel, table=True):
    __tablename__ = "dispatch_worker_heartbeats"

    id: str = Field(primary_key=True, max_length=120)
    label: str = Field(default="", max_length=160)
    host: str = Field(default="", max_length=200)
    capabilities_json: str = Field(default="[]")
    supports_isolated_execution: bool = Field(default=False)
    dispatch_enabled: bool = Field(default=True)
    auth_key_id: str = Field(default="", max_length=120)
    status: str = Field(default="online", max_length=30)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    metadata_json: str = Field(default="{}")


class DispatchExecutionResult(SQLModel, table=True):
    __tablename__ = "dispatch_execution_results"

    id: str = Field(primary_key=True, max_length=64)
    audit_id: str = Field(index=True, max_length=64)
    dispatch_request_id: str = Field(index=True, max_length=64)
    worker_id: str = Field(default="", index=True, max_length=120)
    status: str = Field(default="unknown", max_length=40)
    result_summary: str = Field(default="")
    result_json: str = Field(default="{}")
    error: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
