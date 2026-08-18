#!/usr/bin/env bash
#
# Deploy the financial planner to Cloud Run (Model A: self-hosted FastAPI).
#
# The planner serves A2A at /a2a/financial_planner (card at the standard
# /.well-known/agent-card.json path) — no pickling, no reasoning-engine
# schema hacks. The supervisor's RemoteA2aAgent consumes it directly.
#
# Requires gcloud + docker. Sources deploy.personal.env for PROJECT_ID /
# REGION / ARTIFACT_REGISTRY / ARTIFACT_REGION / SERVICE_NAME and the runtime
# env vars (AGENT_MODEL, MODEL_LOCATION, MCP_PORTFOLIO_URL).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/deploy.personal.env"

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

echo "Pushing image..."
docker push "$IMAGE"

# Deploy. Cloud Run injects PORT; the app binds 0.0.0.0.
# --allow-unauthenticated: the A2A card + JSON-RPC are public. The supervisor
# still authenticates to Vertex AI with its own Bearer token for model calls;
# this service itself carries no secrets.
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 1 \
  --max-instances 1 \
  --update-env-vars "AGENT_MODEL=${AGENT_MODEL},MODEL_LOCATION=${MODEL_LOCATION},MCP_PORTFOLIO_URL=${MCP_PORTFOLIO_URL}"

SERVICE_URL="https://${SERVICE_NAME}-${PROJECT_ID:0:6}.${REGION}.run.app"
echo "Deployed: ${SERVICE_URL}"
echo "A2A card: ${SERVICE_URL}/a2a/financial_planner/.well-known/agent-card.json"
echo "Point the supervisor's FINANCIAL_PLANNER_BASE_URL at: ${SERVICE_URL}"
