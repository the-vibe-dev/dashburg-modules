#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/trends-runtime"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
cp -n .env.example .env || true
trend-harvester migrate
echo "Trends runtime installed. Start with: uvicorn trend_harvester.main:app --host 0.0.0.0 --port 8400"
