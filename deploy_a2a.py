"""Deploy the financial planner as an A2A agent on Agent Runtime.

Uses the Agent Platform SDK object deploy: per the GEAP deploy docs,
``agent_framework`` is auto-detected (as ``a2a``) only when deploying from an
agent object, and that detection is what registers the A2A operations
(``on_message_send`` / ``on_get_task`` / ``on_cancel_task``).

Run via ``deploy.a2a.sh`` (office) or ``deploy.personal.a2a.sh`` (personal),
which source the matching ``*.env`` file first. That file's ``REGION`` is the
authority for where the agent is deployed -- an engine's region is fixed at
creation, so guessing it wrong is not recoverable.

Note: the deploy docs warn against passing GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, PORT or anything prefixed GOOGLE_CLOUD_AGENT_ENGINE as
env vars, so ENV_VARS below deliberately omits them.
"""

from __future__ import annotations

import os

import agentplatform
from google.genai import types

from app.a2a_app import a2a_agent

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]

# Deliberately not read from GOOGLE_CLOUD_LOCATION. That variable is frequently
# already present in the ambient environment (a local .env, a shell export) and
# can disagree with the environment being deployed to. Missing REGION means this
# module was run directly instead of through a wrapper, so fail instead of
# silently deploying into whatever region happens to be exported.
try:
    REGION = os.environ["REGION"]
except KeyError:
    raise SystemExit(
        "REGION is not set - run ./deploy.a2a.sh (office) or "
        "./deploy.personal.a2a.sh (personal) so the wrapper supplies it."
    ) from None

# Keep every other consumer pointed at the same region for the rest of this
# process, so an inherited GOOGLE_CLOUD_LOCATION cannot disagree later.
os.environ["GOOGLE_CLOUD_LOCATION"] = REGION
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_LOCATION"] = REGION

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

DISPLAY_NAME = "akapal-financial-planner"

CONFIG = {
    "display_name": DISPLAY_NAME,
    "description": (
        "Goals-based financial planning agent exposed over A2A on Agent Runtime."
    ),
    "requirements": REQUIREMENTS,
    "extra_packages": EXTRA_PACKAGES,
    "staging_bucket": STAGING_BUCKET,
    "env_vars": ENV_VARS,
    "min_instances": 1,
    "max_instances": 1,
}

client = agentplatform.Client(
    project=PROJECT_ID,
    location=REGION,
    http_options=types.HttpOptions(api_version="v1beta1"),
)

print(f"Project        : {PROJECT_ID}")
print(f"Region         : {REGION}")
print(f"Client location: {getattr(client._api_client, 'location', '?')}")
print(f"Display name   : {DISPLAY_NAME}")
print(f"Staging bucket : {STAGING_BUCKET}")


def _engines_in_region() -> list[str]:
    """Resource names for DISPLAY_NAME, skipping any from another region.

    list() is already region-scoped, so a skipped match means the client and the
    engine disagree about the region -- worth seeing rather than silently
    updating the wrong resource.
    """
    names = []
    for engine in client.agent_engines.list(
        config={"filter": f'display_name="{DISPLAY_NAME}"'}
    ):
        name = engine.api_resource.name
        if f"/locations/{REGION}/" in name:
            names.append(name)
        else:
            print(f"  (skipping match from another region: {name})")
    return names


# Update the existing engine instead of creating another one: the supervisor
# holds this resource name in FINANCIAL_PLANNER_ENGINE, so a brand-new engine on
# every deploy silently invalidates that value.
matches = _engines_in_region()

if len(matches) > 1:
    raise SystemExit(
        f"{len(matches)} engines named {DISPLAY_NAME!r} already exist:\n  "
        + "\n  ".join(matches)
        + "\n\nDelete the superseded ones and re-run, so this deploy updates a "
        "single engine rather than one the supervisor may not be calling."
    )

if matches:
    remote = client.agent_engines.update(
        name=matches[0], agent=a2a_agent, config=CONFIG
    )
    action = "Updated"
else:
    remote = client.agent_engines.create(agent=a2a_agent, config=CONFIG)
    action = "Created"

resource_name = remote.api_resource.name
a2a_base = f"https://{REGION}-aiplatform.googleapis.com/v1beta1/{resource_name}/a2a"

print(f"{action} engine : {resource_name}")
print(f"A2A base    : {a2a_base}")
print(f"A2A card    : {a2a_base}/v1/card")

if f"/locations/{REGION}/" not in resource_name:
    print(
        f"WARNING: {resource_name} is not in {REGION} - check the region before "
        "pointing FINANCIAL_PLANNER_ENGINE at it."
    )
else:
    print("\nFINANCIAL_PLANNER_ENGINE keeps this value across deploys.")
