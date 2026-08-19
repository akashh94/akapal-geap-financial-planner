#!/usr/bin/env bash
#
# Build the financial planner for the OFFICE environment (Cloud Run / Model A).
#
# Sources geap.deploy.env for PROJECT_ID / REGION / ARTIFACT_REGISTRY /
# ARTIFACT_REGION and ensures the Artifact Registry repository exists so the
# image can be pushed.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/geap.deploy.env"

# Office Artifact Registry naming — set these in geap.deploy.env.
ARTIFACT_REGION="${ARTIFACT_REGION:-${REGION}}"
ARTIFACT_REGISTRY="${ARTIFACT_REGISTRY:-akapal-geap-ui}"

IMAGE="${ARTIFACT_REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REGISTRY}/akapal-financial-planner:$(git rev-parse --short HEAD)"

# Ensure the Artifact Registry repository exists.
gcloud artifacts repositories describe "$ARTIFACT_REGISTRY" \
  --location "$ARTIFACT_REGION" >/dev/null 2>&1 || {
  echo "Repository not found; creating..."
  gcloud artifacts repositories create "$ARTIFACT_REGISTRY" \
    --repository-format docker \
    --location "$ARTIFACT_REGION"
}

echo "Building image: ${IMAGE}"
docker build -t "$IMAGE" .
