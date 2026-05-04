#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/skilledagents-runtime"
source .venv/bin/activate
export SKILLEDAGENTS_PORT="${SKILLEDAGENTS_PORT:-8787}"
exec python -m skilledagents.api
