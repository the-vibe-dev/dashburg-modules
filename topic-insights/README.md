# TopicInsights

Installable Dashburg module pack.

## What is included
- Dashburg host module glue
- Bundled local Topic/OIE runtime source in `files/services/topic-insights-runtime/`
- No separate network host is required if you run the bundled service locally

## Dependencies
- Modules: none
- Core capabilities: none

## Host install
```bash
cd ~/apps/dashgithub
./scripts/manage_modules.sh install topic-insights
```

## Local runtime setup
```bash
cd ~/apps/dashgithub/services/topic-insights-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
python -m apps.cli.main db-init --reset
```

## Start local runtime
```bash
cd ~/apps/dashgithub/services/topic-insights-runtime
source .venv/bin/activate
uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
```

## Host env
Set in `~/apps/dashgithub/.env`:
```bash
TOPIC_BASE_URL=http://127.0.0.1:8080
```

## Validation
- Health: `curl http://127.0.0.1:8080/api/v1/health`
- Host module: `curl http://127.0.0.1:8431/api/module-system/validate -X POST -H 'content-type: application/json' -d '{"key":"topic-insights"}'`

## Notes
- This bundle is sourced from the local `newtopic` OIE codebase.
- `idea-factory` and `ideavault` use this local runtime instead of a remote Topic API.
