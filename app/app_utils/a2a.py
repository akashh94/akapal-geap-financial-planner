"""Attach A2A (Agent2Agent) endpoints to the Financial Planner FastAPI app.

Mirrors geap_agent/app/app_utils/a2a.py: registers the dynamic agent-card
endpoint and the JSON-RPC endpoint so A2A clients (including the GEAP
supervisor) can reach this agent.
"""

from __future__ import annotations

import contextvars
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types import AgentCapabilities, AgentCard, AgentExtension
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
)
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder

if TYPE_CHECKING:
    from a2a.server.tasks.task_store import TaskStore
    from fastapi import FastAPI
    from google.adk.agents import BaseAgent
    from google.adk.runners import Runner
    from starlette.requests import Request
    from starlette.responses import Response

_ADK_AGENT_EXECUTOR_EXTENSION_URI = (
    "https://google.github.io/adk-docs/a2a/a2a-extension/"
)

# Captures the scheme+host of the most recent request so the agent card can
# advertise a JSON-RPC URL that the client can actually reach, even when the
# service sits behind a load balancer or proxy.
_request_base_url: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "a2a_request_base_url", default=None
)


def _default_capabilities() -> AgentCapabilities:
    """Returns the default A2A capabilities used by scaffolded projects."""
    return AgentCapabilities(
        streaming=True,
        extensions=[
            AgentExtension(
                uri=_ADK_AGENT_EXECUTOR_EXTENSION_URI,
                description=("Ability to use the new agent executor implementation"),
            ),
        ],
    )


def install_request_base_url_middleware(app: FastAPI) -> None:
    """Capture the incoming request's scheme+host into a contextvar.

    Must be called before the application starts (i.e. at module import),
    because FastAPI rejects middleware registration after startup. The A2A
    agent-card route uses the captured value to advertise a JSON-RPC URL the
    client can actually reach.
    """
    @app.middleware("http")
    async def _capture_request_base_url(
        request: Request, call_next: Callable
    ) -> Response:
        scheme = request.url.scheme or "http"
        host = request.headers.get("host") or request.url.netloc
        token = _request_base_url.set(f"{scheme}://{host}")
        try:
            return await call_next(request)
        finally:
            _request_base_url.reset(token)


async def attach_a2a_routes(
    app: FastAPI,
    *,
    agent: BaseAgent,
    runner: Runner,
    task_store: TaskStore,
    rpc_path: str,
    capabilities: AgentCapabilities | None = None,
    agent_version: str | None = None,
    app_url: str | None = None,
) -> None:
    """Register A2A routes (JSON-RPC + agent-card endpoints) under ``rpc_path``."""
    resolved_agent_version = agent_version or os.getenv("AGENT_VERSION", "0.1.0")
    resolved_capabilities = capabilities or _default_capabilities()

    # The agent card's advertised JSON-RPC URL must point at this service's
    # public address so A2A clients (e.g. the GEAP supervisor's
    # RemoteA2aAgent) can reach it. Prefer APP_URL (the canonical deployed
    # URL); otherwise derive the scheme/host from the incoming request so the
    # card is correct behind load balancers and proxies. A placeholder is
    # used at build time and rewritten per-request via card_modifier.
    resolved_app_url = app_url or os.getenv("APP_URL") or "http://localhost"

    agent_card = await AgentCardBuilder(
        agent=agent,
        capabilities=resolved_capabilities,
        rpc_url=f"{resolved_app_url}{rpc_path}",
        agent_version=resolved_agent_version,
    ).build()

    # The A2A card_modifier hook only receives the card, so it reads the
    # request's base URL from the contextvar set by
    # install_request_base_url_middleware() (registered at import time).
    async def _rewrite_card_url(card: AgentCard) -> AgentCard:
        """Point the card's JSON-RPC URL at the host the client actually used."""
        if app_url or os.getenv("APP_URL"):
            # Explicitly configured URL wins; card is already correct.
            return card
        base = _request_base_url.get()
        if not base:
            return card
        for interface in card.supported_interfaces:
            interface.url = f"{base}{rpc_path}"
        return card

    request_handler = DefaultRequestHandler(
        agent_executor=A2aAgentExecutor(runner=runner),
        task_store=task_store,
        agent_card=agent_card,
    )

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card,
            card_modifier=_rewrite_card_url,
            card_url=f"{rpc_path}{AGENT_CARD_WELL_KNOWN_PATH}",
        ),
        jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url=rpc_path),
    )
