# Dashburg Modules

Installable module packs for `dashburg-public` / `dashgithub`.

Each module directory contains:
- `dashburg-module.json`: manifest and dependency contract
- `files/`: file payload copied into the host repo during install
- `README.md`: setup notes for the module

## Required layout
These module packs are discovered by `dashburg-public` from a sibling clone:

```bash
~/apps/dashgithub
~/apps/dashburg-modules
```

## Public install walkthrough
Read:
- [`PUBLIC_INSTALL.md`](/home/trilobyte/apps/dashburg-modules/PUBLIC_INSTALL.md)

Per-module setup still lives in each module directory:
- `topic-insights/README.md`
- `trends-researcher/README.md`
- `skilled-agents/README.md`
- `discord-control/README.md`
- `webagent/README.md`
- `schedule-ops/README.md`
- `ideavault/README.md`
- `idea-factory/README.md`
