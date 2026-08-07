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

export PROJECT_ID="${PROJECT_ID:-labs-gcp-msls-16495-1782829337}"
export REGION="${REGION:-us-east1}"

gcloud config set project "$PROJECT_ID"

# Matches app/config/models.py's build_model() defaults; override before
# running if you want the deployed agent to use a different model/location.
export AGENT_MODEL="${AGENT_MODEL:-gemini-3.5-flash}"
export MODEL_LOCATION="${MODEL_LOCATION:-global}"

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
