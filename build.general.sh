#!/usr/bin/env bash

set -euo pipefail

# Resolve this project's root (where agents-cli-manifest.yaml lives) and run
# agents-cli from there, so the manifest and pyproject.toml are found
# regardless of the cwd.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# uv resolves the project environment from VIRTUAL_ENV if set. When this
# script runs from a shell where a venv in a parent directory is active,
# uv complains that the interpreter is "outside the project directory".
# Unset it so uv uses the project-local .venv instead.
unset VIRTUAL_ENV

# Office environment config (self-contained): PROJECT_ID / REGION / AGENT_MODEL /
# MODEL_LOCATION / MCP_PORTFOLIO_URL all come from deploy.office.env — the
# single source of truth for the office deployment.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/deploy.office.env"

gcloud config set project "$PROJECT_ID"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v agents-cli >/dev/null 2>&1; then
  echo "agents-cli not found; installing via uv tool install..."
  uv tool install google-agents-cli
  export PATH="$HOME/.local/bin:$PATH"
fi

agents-cli install
agents-cli lint
