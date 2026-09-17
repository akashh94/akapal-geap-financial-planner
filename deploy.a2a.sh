#!/usr/bin/env bash
#
# Deploy the financial planner to Agent Runtime as a native A2A agent (Path A).
#
# The platform owns the A2A surface (on_message_send / on_get_task /
# on_cancel_task under {engine}/a2a/v1/...) and the authenticated card at
# {engine}/a2a/v1/card. Agent Runtime serves no public .well-known card, so the
# supervisor reaches this engine through the Agent Platform SDK rather than by
# fetching a card.
#
# The Cloud Run deployment (deploy.personal.cloudrun.sh) is unaffected — the
# two can run side by side, which is the rollback path.
#
# Sources geap.deploy.env for the office project's values.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# uv resolves the project environment from VIRTUAL_ENV if set. When this
# script runs from a shell where a venv in a parent directory is active, uv
# complains that the interpreter is "outside the project directory". Unset it
# so uv uses the project-local .venv instead.
unset VIRTUAL_ENV

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/geap.deploy.env"

# deploy_a2a.py reads the GOOGLE_CLOUD_* names the SDK expects; the env file
# uses the shorter PROJECT_ID / REGION pair.
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"

gcloud config set project "$PROJECT_ID"

uv run python deploy_a2a.py
