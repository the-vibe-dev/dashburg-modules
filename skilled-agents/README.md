# Skilled Agents

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Bundled local SkilledAgents runtime source in `files/services/skilledagents-runtime/`
- No separate network host is required if you run the bundled service locally

## Dependencies
- Modules: none
- Core capabilities: none

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install skilled-agents
```

## Local runtime setup
```bash
cd ~/apps/dashgithub/services/skilledagents-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Start local runtime
```bash
cd ~/apps/dashgithub/services/skilledagents-runtime
source .venv/bin/activate
export SKILLEDAGENTS_PORT=8787
python -m skilledagents.api
```

## Host env
Set in `~/apps/dashgithub/.env`:
```bash
SKILLED_AGENTS_BASE_URL=http://127.0.0.1:8787
```

## Validation
- Health route from local service
- Host module: `./scripts/manage_modules.sh validate skilled-agents`

## Notes
- This bundle is sourced from the local `~/skilledagents` repo.
- If you want auth, set `SKILLEDAGENTS_API_KEY` in both the runtime and host env.

## User service template
- Template file: `systemd/dashburg-module-skilled-agents.service.template`
- Host-side install: `~/apps/dashgithub/scripts/manage_modules.sh runtime-install-service skilled-agents`
- Host-side start: `~/apps/dashgithub/scripts/manage_modules.sh runtime-start-service skilled-agents`
