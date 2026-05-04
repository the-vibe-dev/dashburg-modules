#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../files/services/skilledagents-runtime"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
echo "SkilledAgents runtime installed. Start with: python -m skilledagents.api"
