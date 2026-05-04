#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/discord-bridge-runtime"
source .venv/bin/activate
export DISCORD_DASHBURG_BASE_URL="${DISCORD_DASHBURG_BASE_URL:-http://127.0.0.1:8431}"
export DISCORD_BRIDGE_PORT="${DISCORD_BRIDGE_PORT:-9101}"
exec python discord_bridge.py
