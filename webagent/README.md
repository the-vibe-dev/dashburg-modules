# WebAgent

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Local UI/backend routes
- Uses the local Dashburg runner as the execution node instead of a separate upstream API

## Dependencies
- Modules: none
- Core capabilities: `remote-ops`

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install webagent
```

## Local runtime setup
- Install and run the Dashburg runner on the same device
- Register or configure a local RemoteOps node with id or label `webagent`

## Start local runtime
```bash
cd ~/apps/dashgithub/runner
./.venv/bin/python run.py
```

## Validation
- Runner reachable on `127.0.0.1:8444`
- WebAgent module validates with `./scripts/manage_modules.sh validate webagent`

## Notes
- WebAgent is local-only when the runner and the node record are on the same host.
- No separate webagent HTTP backend is needed beyond Dashburg host + runner.
