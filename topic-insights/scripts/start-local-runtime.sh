#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/topic-insights-runtime"
source .venv/bin/activate
exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
