"""Deploy the financial planner as an A2A agent on Agent Runtime.

Uses the Agent Platform SDK object deploy: per the GEAP deploy docs,
``agent_framework`` is auto-detected (as ``a2a``) only when deploying from an
agent object, and that detection is what registers the A2A operations
(``on_message_send`` / ``on_get_task`` / ``on_cancel_task``).

Run via ``deploy.a2a.sh`` (office) or ``deploy.personal.a2a.sh`` (personal),
both of which source the matching ``*.env`` file first.

Note: the deploy docs warn against passing GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, PORT or anything prefixed GOOGLE_CLOUD_AGENT_ENGINE as
env vars, so ENV_VARS below deliberately omits them.
"""

from __future__ import annotations

import os

import vertexai
from google.genai import types

from app.a2a_app import a2a_agent

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Required for the object deploy: Agent Runtime stages the pickled agent, the
# requirements file and any dependency files under this bucket.
STAGING_BUCKET = os.environ["STAGING_BUCKET"]

ENV_VARS = {
    key: os.environ[key]
    for key in (
        "AGENT_MODEL",
        "MODEL_LOCATION",
        "MCP_PORTFOLIO_URL",
        "MCP_REGISTRY_PROJECT_ID",
        "MCP_REGISTRY_LOCATION",
        "MCP_REGISTRY_SERVER",
        "MEMORY_BANK_ID",
    )
    if os.environ.get(key)
}

# Mirrors the repo's pyproject runtime set, so the deployed container matches
# the environment the entrypoint is verified against. pydantic and cloudpickle
# are required by the SDK's object-deploy packaging.
REQUIREMENTS = [
    "google-adk[gcp,db,a2a,agent-identity]==2.6.2",
    "google-cloud-aiplatform[agent_engines,adk]==1.163.0",
    "google-cloud-firestore",
    "google-genai==2.17.0",
    "python-dotenv",
    "a2a-sdk",
    "fastapi",
    "uvicorn[standard]",
    "sse-starlette",
    "mcp>=1.24,<2",
    "pydantic",
    "cloudpickle",
]

# The object deploy only ships the pickle and requirements by default, so the
# `app` package must be bundled explicitly — otherwise the container fails with
# "No module named 'app.a2a_app'" because the pickled references to
# build_runner / build_agent_executor cannot be resolved.
EXTRA_PACKAGES = ["app"]

client = vertexai.Client(
    project=PROJECT_ID,
    location=REGION,
    http_options=types.HttpOptions(api_version="v1beta1"),
)

remote = client.agent_engines.create(
    agent=a2a_agent,
    config={
        "display_name": "akapal-financial-planner",
        "description": (
            "Goals-based financial planning agent exposed over A2A on Agent Runtime."
        ),
        "requirements": REQUIREMENTS,
        "extra_packages": EXTRA_PACKAGES,
        "staging_bucket": STAGING_BUCKET,
        "env_vars": ENV_VARS,
        "min_instances": 1,
        "max_instances": 1,
    },
)

resource_name = remote.api_resource.name
a2a_base = f"https://{REGION}-aiplatform.googleapis.com/v1beta1/{resource_name}/a2a"

print(f"A2A engine : {resource_name}")
print(f"A2A base   : {a2a_base}")
print(f"A2A card   : {a2a_base}/v1/card")
print(
    "\nPoint the supervisor's FINANCIAL_PLANNER_ENGINE at the resource name above."
)
