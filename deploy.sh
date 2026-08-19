#!/usr/bin/env bash
#
# Deploy the financial planner to Cloud Run (Model A) for the OFFICE environment.
#
# Sources geap.deploy.env for PROJECT_ID / REGION / ARTIFACT_REGISTRY /
# ARTIFACT_REGION / SERVICE_NAME / APP_URL and the runtime env vars
# (AGENT_MODEL, MODEL_LOCATION, MCP_PORTFOLIO_URL, MCP_REGISTRY_*).
#
# The planner serves A2A at /a2a/financial_planner (card at the standard
# /.well-known/agent-card.json path). APP_URL must be the public https URL so
# the card advertises an endpoint A2A clients can actually reach.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/geap.deploy.env"

ARTIFACT_REGION="${ARTIFACT_REGION:-${REGION}}"
ARTIFACT_REGISTRY="${ARTIFACT_REGISTRY:-akapal-geap-ui}"
SERVICE_NAME="${SERVICE_NAME:-akapal-financial-planner}"

IMAGE="${ARTIFACT_REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REGISTRY}/akapal-financial-planner:$(git rev-parse --short HEAD)"

echo "Building image: ${IMAGE}"
docker build -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

# Cloud Run injects PORT; the app binds 0.0.0.0.
# --allow-unauthenticated: the A2A card + JSON-RPC are public. The supervisor
# still authenticates to Vertex AI with its own Bearer token for model calls.
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --min-instances 1 \
  --max-instances 1 \
  --update-env-vars "AGENT_MODEL=${AGENT_MODEL},MODEL_LOCATION=${MODEL_LOCATION},MCP_PORTFOLIO_URL=${MCP_PORTFOLIO_URL},MCP_REGISTRY_PROJECT_ID=${MCP_REGISTRY_PROJECT_ID},MCP_REGISTRY_LOCATION=${MCP_REGISTRY_LOCATION},MCP_REGISTRY_SERVER=${MCP_REGISTRY_SERVER},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},APP_URL=${APP_URL}"

SERVICE_URL="https://${SERVICE_NAME}-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)').${REGION}.run.app"
echo "Deployed: ${SERVICE_URL}"
echo "A2A card: ${SERVICE_URL}/a2a/financial_planner/.well-known/agent-card.json"
echo "Point the supervisor's FINANCIAL_PLANNER_BASE_URL at: ${SERVICE_URL}/a2a/financial_planner"
