#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/discord-bridge-runtime"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
echo "Discord bridge runtime installed. Export DISCORD_TOKEN before start."
