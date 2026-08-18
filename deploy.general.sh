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
# MODEL_LOCATION / MCP_PORTFOLIO_URL all come from geap.deploy.env — the
# single source of truth for the office deployment. Note: the general env
# file still points MCP_PORTFOLIO_URL at an old SSE endpoint; update it to the
# Streamable HTTP /mcp URL before deploying this target.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/geap.deploy.env"

# "agent_runtime" is the target that maps to the Vertex AI Agent Engine /
# Reasoning Engine resource that geap-poc/server.js already calls
# (GEAP_ENGINE_ID et al.).
agents-cli deploy \
  --deployment-target agent_runtime \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "AGENT_MODEL=${AGENT_MODEL},MODEL_LOCATION=${MODEL_LOCATION},MCP_PORTFOLIO_URL=${MCP_PORTFOLIO_URL}" \
  --no-confirm-project
