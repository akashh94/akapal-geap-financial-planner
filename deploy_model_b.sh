#!/usr/bin/env bash
#
# Deploy the financial planner to Vertex AI Agent Engine as an A2A agent
# (Model B: A2aAgent + ReasoningEngine.create, agent card hosted natively).
#
# Sources the environment (deploy.personal.env or geap.deploy.env) for
# PROJECT_ID / REGION, then runs app/deploy_a2a.py which wraps the ADK agent
# in an A2aAgent and deploys it via ReasoningEngine.create().
#
# Requires STAGING_BUCKET (a GCS bucket for staging the engine artifacts):
#   STAGING_BUCKET=gs://my-bucket ./deploy_model_b.sh

set -euo pipefail

# Resolve this project's root (where pyproject.toml lives) and run from there.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Env file: first CLI arg, else deploy.personal.env (gitignored), else geap.deploy.env.
ENV_FILE="${1:-geap.deploy.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
else
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

# STAGING_BUCKET is required (Vertex AI stages the engine build there).
if [[ -z "${STAGING_BUCKET:-}" ]]; then
  echo "STAGING_BUCKET is required (e.g. gs://<bucket>)" >&2
  exit 1
fi

python app/deploy_a2a.py
