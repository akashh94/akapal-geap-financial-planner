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


# Matches app/config/models.py's build_model() defaults; override before
# running if you want the deployed agent to use a different model/location.
export AGENT_MODEL="${AGENT_MODEL:-gemini-2.0-flash}"
export MODEL_LOCATION="${MODEL_LOCATION:-global}"
export MCP_PORTFOLIO_URL="${MCP_PORTFOLIO_URL:-https://mcp-portfolio-492310803820.us-east1.run.app/sse}"

# agents-cli-manifest.yaml has deployment_target set to "none" (never wired
# up), so it's overridden explicitly here. "agent_runtime" is the target that
# maps to the Vertex AI Agent Engine / Reasoning Engine resource that
# geap-poc/server.js already calls (GEAP_ENGINE_ID et al.).
agents-cli deploy \
  --deployment-target agent_runtime \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "AGENT_MODEL=${AGENT_MODEL},MODEL_LOCATION=${MODEL_LOCATION},MCP_PORTFOLIO_URL=${MCP_PORTFOLIO_URL}" \
  --no-confirm-project
