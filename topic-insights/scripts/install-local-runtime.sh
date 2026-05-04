#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/topic-insights-runtime"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp -n .env.example .env || true
python -m apps.cli.main db-init --reset
echo "TopicInsights runtime installed. Start with: uvicorn apps.api.main:app --host 0.0.0.0 --port 8080"
