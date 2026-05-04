# SkilledAgents API

Base URL: `http://<host>:<port>`

Auth:
- If `SKILLEDAGENTS_API_KEY` is set on server, send header `X-API-Key: <value>`.
- If not set, API runs without auth (dev mode only).

## Endpoints

### Health
- `GET /health`

Response example:
```json
{
  "ok": true,
  "service": "skilledagents",
  "time": "2026-03-08T16:55:00.000000+00:00",
  "db_path": "/srv/skilledagents/data/skilledagents.sqlite3",
  "agents_count": 3
}
```

### Skills
- `GET /skills`
- `GET /skills/{skill_id}`

`GET /skills` response example:
```json
[
  {
    "id": "qwen-tts",
    "name": "qwen-tts",
    "description": "Local text-to-speech using Qwen3-TTS...",
    "path": "/home/trilobyte/.codex/skills/qwen-tts"
  }
]
```

### Templates
- `GET /templates`
- `GET /templates/{template_id}`

`GET /templates` response example:
```json
[
  {
    "id": "marketing-ideas-agent",
    "name": "Marketing Ideas Agent",
    "description": "Generates campaign concepts...",
    "category": "marketing",
    "strict_by_default": true
  }
]
```

### Starter Templates (Registry-driven)
- `GET /starter-templates`
- `GET /starter-templates/{slug}`
- `POST /starter-templates/import`
- `POST /starter-templates/import-batch`

Import payload example:
```json
{
  "zip_path": "/srv/skilledagents/imports/skilledagents_starter_pack_v2.zip"
}
```

Batch import payload example:
```json
{
  "zip_paths": [
    "/srv/skilledagents/imports/skilledagents_starter_pack_v1.zip",
    "/srv/skilledagents/imports/skilledagents_starter_pack_v2.zip",
    "/srv/skilledagents/imports/skilledagents_starter_pack_v3_additions.zip"
  ]
}
```

### Agents
- `POST /agents`
- `POST /agents/from-template`
- `POST /agents/preview-from-template`
- `GET /agents`
- `GET /agents/{agent_id}`
- `PATCH /agents/{agent_id}`
- `POST /agents/{agent_id}/skills`
- `DELETE /agents/{agent_id}/skills/{skill_id}`
- `POST /agents/{agent_id}/prepare`
- `POST /agents/{agent_id}/deploy`
- `POST /agents/{agent_id}/run`
- `POST /agents/{agent_id}/stop`
- `GET /agents/{agent_id}/logs`
- `GET /agents/{agent_id}/status`
- `GET /agents/{agent_id}/workspace`
- `GET /agents/{agent_id}/manifest`
- `GET /agents/{agent_id}/snapshots`
- `GET /agents/{agent_id}/latest-snapshot`
- `POST /agents/{agent_id}/run-validation`
- `POST /agents/{agent_id}/run-smoke-test`

Create agent payload example:
```json
{
  "name": "Repo Auditor",
  "slug": "repo-auditor",
  "description": "Scans repos for risk",
  "agent_type": "auditor",
  "runtime": "python",
  "model_provider": "openai",
  "model_name": "gpt-5",
  "model_settings": {
    "temperature": 0.2
  },
  "selected_skills": ["skill-creator"],
  "env_config": {
    "LOG_LEVEL": "INFO"
  },
  "flags": {
    "strict_mode": true
  },
  "network_access": false,
  "sandbox_mode": "workspace-write",
  "yolo_mode": false,
  "template_id": "marketing-ideas-agent",
  "specialization_mode": "strict",
  "role_identity": "marketing_ideas_agent",
  "domain_focus": "marketing ideation",
  "execution_mode": "brainstorm",
  "allowed_tools": ["filesystem", "markdown_writer"],
  "runtime_policies": {
    "max_output_items": 20
  },
  "saved_prompts": {
    "system": "You are a focused marketing ideation agent."
  },
  "specialization_metadata": {
    "notes": "initial rollout"
  }
}
```

Attach skill payload:
```json
{
  "skill_id": "qwen-tts"
}
```

Patch agent payload example:
```json
{
  "description": "Updated description",
  "flags": {
    "strict_mode": false
  },
  "network_access": true
}
```

Run payload examples:
```json
{
  "command": "python3",
  "args": ["main.py", "--mode", "batch"]
}
```

```json
{}
```

Logs query example:
- `GET /agents/{agent_id}/logs?limit=500`
- `GET /agents/{agent_id}/logs?run_id=<run_id>&limit=200`

## Semantics

- `prepare`: creates workspace, attaches selected skills, writes manifest, installs `requirements.txt` if present.
- `deploy`: finalizes runtime-ready state and rewrites manifest.
- `run`: starts a process in workspace and records run metadata + logs.
- `stop`: terminates active process if one exists.
- templates: define specialization defaults (recommended skills, disallowed capabilities, prompts, UI hints).
- strict specialization mode:
  - template constraints are enforced (for example network/yolo disallowed flags, allowed skill set).
  - role identity is preserved unless switched to custom mode.
- custom specialization mode:
  - template identity stays attached, but advanced overrides are allowed and recorded in specialization metadata.
- starter template preview (`POST /agents/preview-from-template`) returns:
  - `files_to_create`
  - `skills_to_attach`
  - `dependencies_to_install`
  - `recommended_deploy_mode`
  - `final_execution_mode`
  - `entrypoint`
  - `compatibility_badges`
  - `external_dependencies`
  - `uses_webagent`
- deploy snapshots (`/agents/{id}/snapshots`) capture:
  - selected skills
  - skill versions (if supplied)
  - installed requirements
  - runtime flags
  - entrypoint
- optional checks:
  - validation hook (`run-validation`)
  - smoke test command (`run-smoke-test`)
  - latest results are persisted in `agent.flags`

## Starter Pack Merge Rules

- v1 acts as base starter pack.
- v2 is preferred on overlap (higher precedence).
- v3 additions are merge-only and do not replace existing slugs.
- provenance is preserved in registry/history:
  - source zip path
  - pack version
  - template version
  - import timestamp
  - action (`inserted`, `replaced`, `skipped_*`)

## WebAgent-backed Starter Templates

- Templates can declare `uses_webagent` and delegated Playwright behavior.
- These templates are represented as delegated-browser execution, not forced local browser runtime.
- External dependency hints include WebAgent Playwright analyzer metadata when applicable.

Status values (current set):
- `created`
- `preparing`
- `prepared`
- `deploying`
- `deployed`
- `running`
- `idle`
- `stopped`
- `error`

## Dashburg Integration Flow (Wizard)

1. Call `GET /health` and `GET /skills`.
2. Create draft via `POST /agents`.
3. Save edits via `PATCH /agents/{id}`.
4. Attach/remove skills with `/skills` linkage endpoints.
5. Execute `POST /agents/{id}/prepare` and poll `GET /agents/{id}/status`.
6. Execute `POST /agents/{id}/deploy`.
7. Execute `POST /agents/{id}/run`.
8. Stream/poll `GET /agents/{id}/logs` and `GET /agents/{id}/status`.
9. Use `POST /agents/{id}/stop` for termination.
10. Show `GET /agents/{id}/manifest` and `/workspace` for diagnostics/audit.

## Local-first Storage

SQLite tables:
- `agents`
- `agent_skills`
- `agent_runs`
- `agent_logs`
- `state_transitions`

Default paths:
- DB: `./skilledagents/data/skilledagents.sqlite3`
- Workspaces: `./skilledagents/workspaces`

Override with env vars:
- `SKILLEDAGENTS_DB_PATH`
- `SKILLEDAGENTS_WORKSPACES_ROOT`
- `SKILLEDAGENTS_SKILLS_ROOT`
- `SKILLEDAGENTS_TEMPLATES_PATH` (optional JSON file for template definitions)
- `SKILLEDAGENTS_STARTER_TEMPLATES_ROOT` (starter template import/cache/registry files)
- `SKILLEDAGENTS_API_KEY`

Recommended starter template root on deployed hosts:
- `/srv/skilledagents/starter_templates/`
