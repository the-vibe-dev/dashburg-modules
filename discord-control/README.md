# Discord Control

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Bundled local Discord bridge runtime in `files/services/discord-bridge-runtime/`
- No separate bridge host is required if you run the bundled bridge locally

## Dependencies
- Modules: none
- Core capabilities: `chat-api`, `memory`, `orchestration`, `remote-ops`

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install discord-control
```

## Local runtime setup
```bash
cd ~/apps/dashgithub/services/discord-bridge-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Start local runtime
```bash
cd ~/apps/dashgithub/services/discord-bridge-runtime
source .venv/bin/activate
export DISCORD_DASHBURG_BASE_URL=http://127.0.0.1:8431
export DISCORD_BRIDGE_PORT=9101
export DISCORD_TOKEN=your_bot_token
python discord_bridge.py
```

## Host env
Set in `~/apps/dashgithub/.env`:
```bash
DISCORD_BRIDGE_BIND=127.0.0.1
DISCORD_BRIDGE_PORT=9101
```

## Validation
- Bridge status route on `127.0.0.1:9101`
- Host module: `./scripts/manage_modules.sh validate discord-control`

## Notes
- The bot token is required for real Discord connectivity.
- This bundle removes the need for a separate bridge host, but not for Discord credentials.

## User service template
- Template file: `systemd/dashburg-module-discord-control.service.template`
- Host-side install: `~/apps/dashgithub/scripts/manage_modules.sh runtime-install-service discord-control`
- Host-side start: `~/apps/dashgithub/scripts/manage_modules.sh runtime-start-service discord-control`
