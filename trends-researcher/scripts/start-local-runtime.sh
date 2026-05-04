#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/trends-runtime"
source .venv/bin/activate
exec uvicorn trend_harvester.main:app --host 0.0.0.0 --port 8400
