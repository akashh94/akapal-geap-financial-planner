"""Deploy the financial planner to Vertex AI Agent Engine as an A2A agent.

Wraps the ADK ``LlmAgent`` (``financial_planner_agent``) in a
``vertexai.agent_engines.templates.a2a.A2aAgent`` — which serves the A2A
protocol (JSON-RPC/HTTP) and hosts the agent card natively on Agent Engine —
then deploys it via ``ReasoningEngine.create()``.

Run from the repo root with the planner's env sourced:

    source deploy.personal.env   # or geap.deploy.env
    python app/deploy_a2a.py

The deployed agent is reachable over A2A at:

    https://<LOCATION>-aiplatform.googleapis.com/v1beta1/
      projects/<PROJECT_ID>/locations/<LOCATION>/
      reasoningEngines/<ENGINE_ID>/a2a
"""

from __future__ import annotations

import os
from typing import cast

import vertexai
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentSkill
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.artifacts.in_memory_artifact_service import (
    InMemoryArtifactService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from vertexai.agent_engines.templates.a2a import A2aAgent, create_agent_card
from vertexai.preview.reasoning_engines import ReasoningEngine
from vertexai.reasoning_engines import _reasoning_engines

from app.agents.financial_planner_agent import financial_planner_agent


def _build_runner() -> Runner:
    """A Runner for the financial planner, using in-memory services."""
    return Runner(
        agent=financial_planner_agent,
        app_name=financial_planner_agent.name,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
        memory_service=InMemoryMemoryService(),
        auto_create_session=True,
    )


def _build_executor(runner: Runner) -> A2aAgentExecutor:
    """ADK A2A executor adapter wrapping the planner's Runner."""
    return A2aAgentExecutor(runner=runner)


def _build_agent_skills() -> list[AgentSkill]:
    """Derive A2A skills from the ADK agent's tools (one skill per tool).

    Only tools with a usable ``name`` contribute a skill; toolsets (e.g. the
    MCP portfolio toolset) are skipped.
    """
    skills = []
    for tool in financial_planner_agent.tools:
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            continue
        skill = AgentSkill(
            id=f"{financial_planner_agent.name}-{tool_name}",
            name=tool_name,
            description=getattr(tool, "description", None)
            or f"Use the {tool_name} tool.",
            tags=["financial_planning"],
        )
        skills.append(skill)
    return skills or [
        AgentSkill(
            id=f"{financial_planner_agent.name}-planning",
            name="financial_planning",
            description="Goals-based financial planning and projections.",
            tags=["financial_planning"],
        )
    ]


def _build_a2a_agent() -> A2aAgent:
    """Wrap the planner in an A2aAgent with a manually-defined agent card."""
    agent_card = create_agent_card(
        agent_name=financial_planner_agent.name,
        description=financial_planner_agent.description,
        skills=_build_agent_skills(),
    )
    return A2aAgent(
        agent_card=agent_card,
        task_store_builder=lambda **kw: InMemoryTaskStore(),
        agent_executor_builder=lambda **kw: _build_executor(_build_runner()),
    )


def main() -> None:
    """Initialize Vertex AI and deploy the A2A planner."""
    project = os.getenv("PROJECT_ID", "")
    location = os.getenv("REGION", os.getenv("GOOGLE_CLOUD_LOCATION", ""))
    staging_bucket = os.getenv("STAGING_BUCKET", "")
    if not (project and location and staging_bucket):
        raise ValueError(
            "PROJECT_ID, REGION (or GOOGLE_CLOUD_LOCATION), and STAGING_BUCKET "
            "must be set (source deploy.personal.env / geap.deploy.env and set "
            "STAGING_BUCKET=gs://...)."
        )

    vertexai.init(
        project=project,
        location=location,
        staging_bucket=staging_bucket,
    )

    a2a_agent = _build_a2a_agent()
    # ty can't see that A2aAgent satisfies the Queryable protocol at runtime.
    a2a_agent_queryable = cast(_reasoning_engines.Queryable, a2a_agent)
    engine = ReasoningEngine.create(
        a2a_agent_queryable,
        display_name=os.getenv("AGENT_DISPLAY_NAME", "financial-planner"),
        requirements=[
            "google-adk[gcp,db,a2a]",
            "google-cloud-aiplatform[agent_engines,adk]",
            "google-genai",
            "a2a-sdk",
            "mcp>=1.24,<2",
        ],
        extra_packages=["."],  # package this repo's app/ source
    )
    print(f"Deployed: {engine.resource_name}")
    print(
        f"A2A endpoint: https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project}/locations/{location}/reasoningEngines/"
        f"{engine.resource_name.rsplit('/', 1)[-1]}/a2a"
    )


if __name__ == "__main__":
    main()
