# IdeaVault

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Local DB models, routes, lineage support, and UI
- Queue handoff into local TopicInsights runtime

## Dependencies
- Modules: `topic-insights`
- Core capabilities: none

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install ideavault
```

## Required local runtime
Start `topic-insights` locally if you want queue/research handoff.

## Validation
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh validate ideavault
```

## Notes
- Basic save/edit/lineage behavior is host-local.
- TopicFactory-style research handoff uses the local TopicInsights service on the same device.
