# ScheduleOps

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Local scheduling control UI and backend routes
- Uses the local Dashburg runner for execution

## Dependencies
- Modules: none
- Core capabilities: `remote-ops`, `orchestration`

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install schedule-ops
```

## Local runtime setup
- Run the Dashburg host
- Run the local runner on the same device

## Validation
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh validate schedule-ops
```

## Notes
- No separate upstream ScheduleOps service is required.
- Real scheduling actions still depend on runner availability.
