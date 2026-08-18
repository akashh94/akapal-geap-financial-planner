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

import inspect
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


def _build_a2a_agent(agent_engine_id: str | None = None) -> A2aAgent:
    """Wrap the planner in an A2aAgent with a manually-defined agent card.

    ``agent_engine_id`` (when known) is baked into both cards' advertised URL
    at construction time — the platform serves the pickled card snapshot, so a
    runtime ``set_up()`` rewrite never reaches consumers.
    """
    agent_card = create_agent_card(
        agent_name=financial_planner_agent.name,
        description=financial_planner_agent.description,
        skills=_build_agent_skills(),
    )
    a2a_agent = A2aAgent(
        agent_card=agent_card,
        extended_agent_card=agent_card,
        task_store_builder=lambda **kw: InMemoryTaskStore(),
        agent_executor_builder=lambda **kw: _build_executor(_build_runner()),
    )
    if agent_engine_id:
        project = os.getenv("PROJECT_ID", "")
        location = os.getenv("REGION", os.getenv("GOOGLE_CLOUD_LOCATION", ""))
        correct_url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{location}/"
            f"reasoningEngines/{agent_engine_id}/a2a"
        )
        cards = [
            card
            for card in (agent_card, a2a_agent._tmpl_attrs.get("extended_agent_card"))
            if card is not None and card.supported_interfaces
        ]
        for card in cards:
            card.supported_interfaces[0].url = correct_url
        a2a_agent._tmpl_attrs["agent_engine_id"] = agent_engine_id
    return a2a_agent


def _any_pydantic_schema(cls, source, handler):
    """Emit an unconstrained core schema for non-pydantic request types.

    ``vertexai.reasoning_engines._utils.generate_schema`` builds a pydantic
    model from each A2A method's annotations. The a2a-sdk request types are
    protobuf messages (no pydantic schema), and gRPC context types are opaque,
    so without this hook pydantic raises and the engine's A2A operations never
    register. ``ponytail:`` this is a schema-generation shim; revisit when
    google-cloud-aiplatform supports protobuf-typed A2A methods natively.
    """
    from pydantic_core import core_schema

    return core_schema.any_schema()


def _make_a2a_operations_registrable(a2a_agent: A2aAgent) -> None:
    """Resolve the A2aAgent's string annotations so operations register.

    The A2aAgent's ``on_*`` methods annotate parameters with forward-reference
    strings (``"SendMessageRequest"``, ``"ServerCallContext"``). Resolve the
    request types to their real protobuf classes (patched with
    ``__get_pydantic_core_schema__``) and map anything else (e.g. gRPC context)
    to ``object`` so ``generate_schema`` succeeds.
    """
    import a2a.types as a2a_types

    patched: set[type] = set()
    for name, member in inspect.getmembers(type(a2a_agent)):
        if not (name.startswith("on_") and callable(member)):
            continue
        annotations = dict(getattr(member, "__annotations__", {}))
        changed = False
        for param, ref in annotations.items():
            if not isinstance(ref, str):
                continue
            resolved = getattr(a2a_types, ref, None) or object
            annotations[param] = resolved
            if (
                resolved is not object
                and isinstance(resolved, type)
                and resolved not in patched
            ):
                resolved.__get_pydantic_core_schema__ = classmethod(
                    _any_pydantic_schema
                )
                patched.add(resolved)
            changed = True
        if changed:
            member.__annotations__ = annotations


def _patch_a2a_set_up_with_standard_routes() -> None:
    """Mount the standard card + JSON-RPC routes on the pickled A2aAgent.

    The ``A2aAgent`` template mounts only the a2a-sdk REST routes
    (``/a2a/message:send`` etc.), so the standard
    ``/.well-known/agent-card.json`` card route and the ``/a2a`` JSON-RPC
    endpoint (which ``RemoteA2aAgent`` expects) are missing. Mirror ADK's
    ``to_a2a()`` / ``attach_a2a_routes_to_app()`` pattern: extend
    ``set_up()`` to also mount ``create_agent_card_routes`` and
    ``create_jsonrpc_routes`` under ``/a2a``. Also override the engine ID used
    in the advertised card URL (the env default ``test-agent-engine`` is wrong
    when the platform doesn't inject ``GOOGLE_CLOUD_AGENT_ENGINE_ID``).
    """
    from a2a.server.request_handlers import RequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

    original_set_up = A2aAgent.set_up

    def set_up_with_standard_routes(self: A2aAgent) -> None:
        original_set_up(self)
        existing = {getattr(route, "path", "") for route in self.rest_routes}
        card_routes = create_agent_card_routes(
            self.agent_card,
            card_url=f"/a2a{AGENT_CARD_WELL_KNOWN_PATH}",
        )
        # set_up() guarantees request_handler is set before we get here.
        jsonrpc_routes = create_jsonrpc_routes(
            cast("RequestHandler", self.request_handler), "/a2a"
        )
        self.rest_routes.extend(
            route
            for route in [*card_routes, *jsonrpc_routes]
            if getattr(route, "path", "") not in existing
        )

    A2aAgent.set_up = set_up_with_standard_routes


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
    _make_a2a_operations_registrable(a2a_agent)
    _patch_a2a_set_up_with_standard_routes()
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
    engine_id = engine.resource_name.rsplit("/", 1)[-1]
    print(f"Deployed: {engine.resource_name}")

    # Second pass: the engine ID is now known, so rebuild the agent with the
    # correct card URL and update the engine in place (the platform doesn't
    # inject GOOGLE_CLOUD_AGENT_ENGINE_ID, so the first pass would advertise
    # the wrong "test-agent-engine" URL in the card).
    a2a_agent_with_id = _build_a2a_agent(agent_engine_id=engine_id)
    _make_a2a_operations_registrable(a2a_agent_with_id)
    _patch_a2a_set_up_with_standard_routes()
    engine.update(
        reasoning_engine=cast(_reasoning_engines.Queryable, a2a_agent_with_id),
    )
    print("Updated with correct card URL.")

    print(
        f"A2A endpoint: https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project}/locations/{location}/reasoningEngines/"
        f"{engine_id}/a2a"
    )


if __name__ == "__main__":
    main()
