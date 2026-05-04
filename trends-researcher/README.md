# TrendsResearcher

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Bundled local trend harvester runtime source in `files/services/trends-runtime/`
- No separate network trends host is required if you run the bundled service locally

## Dependencies
- Modules: none
- Core capabilities: none

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install trends-researcher
```

## Local runtime setup
```bash
cd ~/apps/dashgithub/services/trends-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
cp .env.example .env
trend-harvester migrate
```

## Start local runtime
```bash
cd ~/apps/dashgithub/services/trends-runtime
source .venv/bin/activate
uvicorn trend_harvester.main:app --host 0.0.0.0 --port 8400
```

## Host env
Set in `~/apps/dashgithub/.env`:
```bash
DASHBURG_TRENDS_API_BASE_URL=http://127.0.0.1:8400
```

## Validation
- Health: `curl http://127.0.0.1:8400/api/runs`
- Host module: `./scripts/manage_modules.sh validate trends-researcher`

## Notes
- This bundle is sourced from the local `trend-harvester` codebase.
- Exports into IdeaFactory remain local if both modules are installed.
