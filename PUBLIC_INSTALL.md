# Dashburg Modules Public Install Walkthrough

## 1. Clone beside the host repo
```bash
cd ~/apps
git clone https://github.com/the-vibe-dev/dashburg-public.git dashgithub
git clone https://github.com/the-vibe-dev/dashburg-modules.git dashburg-modules
```

The host repo expects:
```bash
~/apps/dashgithub
~/apps/dashburg-modules
```

## 2. Install the host first
```bash
cd ~/apps/dashgithub
./scripts/install_dashgithub.sh
```

## 3. Install modules into the host
Examples:
```bash
./scripts/manage_modules.sh install topic-insights
./scripts/manage_modules.sh install ideavault
./scripts/manage_modules.sh install trends-researcher
```

## 4. Bootstrap bundled runtimes
Single module:
```bash
./scripts/bootstrap_module_runtime.sh topic-insights
```

All installed bundled runtimes:
```bash
./scripts/bootstrap_module_runtime.sh all
```

## 5. Validate health
```bash
./scripts/manage_modules.sh validate topic-insights
./scripts/manage_modules.sh runtime-status topic-insights
```

## Module runtime map
- `topic-insights`: bundled local service on `127.0.0.1:8080`
- `trends-researcher`: bundled local service on `127.0.0.1:8400`
- `skilled-agents`: bundled local service on `127.0.0.1:8787`
- `discord-control`: bundled local service on `127.0.0.1:9101`
- `webagent`: local runner node
- `schedule-ops`: host + local runner
- `ideavault`: host-only
- `idea-factory`: depends on local `topic-insights`

## Important note
These modules no longer require an upstream host to run, but some still require local credentials or provider configuration:
- Discord bot token for `discord-control`
- LLM/provider config for `topic-insights` and `trends-researcher`
- local service config for `skilled-agents`
