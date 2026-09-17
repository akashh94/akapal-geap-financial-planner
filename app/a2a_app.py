"""Agent Runtime A2A entrypoint for the financial planner.

Built on the documented Agent Runtime A2A template
(``vertexai.agent_engines.templates.a2a.A2aAgent``). The platform owns the A2A
surface — ``on_message_send`` / ``on_get_task`` / ``on_cancel_task`` under
``{engine}/a2a/v1/...`` — and the authenticated card at ``{engine}/a2a/v1/card``.
Agent Runtime deliberately serves no public ``.well-known`` card.

The Cloud Run path (``app/fast_api_app.py`` + ``app/app_utils/a2a.py``) is
untouched and keeps working; this module is the Agent Runtime alternative.
"""

from __future__ import annotations

import logging
import os

from a2a.types import AgentSkill
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.runners import Runner
from google.adk.tools.base_toolset import BaseToolset
from vertexai.agent_engines.templates.a2a import A2aAgent, create_agent_card

from app.agents.financial_planner_agent import build_financial_planner_agent
from app.app_utils import services

logger = logging.getLogger(__name__)

# Written by hand rather than derived from the agent tree: ADK's
# AgentCardBuilder would also advertise every internal tool (load_memory,
# portfolio_service_unavailable, ...) as a skill. Since a peer agent's LLM is
# the reader, these are written to be read.
_SKILLS = [
    AgentSkill(
        id="retirement_readiness",
        name="Retirement readiness",
        description=(
            "Projects whether current savings and contributions reach a target "
            "nest egg by a target age, and how long that portfolio lasts in "
            "retirement."
        ),
        tags=["planning", "retirement"],
        examples=[
            "Can I retire in 10 years if I save $1,000/month?",
            "How long will my savings last if I withdraw $4,000/month?",
        ],
    ),
    AgentSkill(
        id="savings_goal",
        name="Savings goal projection",
        description=(
            "Works out the monthly contribution needed to hit a savings target, "
            "or the balance a given contribution reaches over a number of years."
        ),
        tags=["planning", "savings"],
        examples=["What do I need to save monthly to reach $1,000,000?"],
    ),
    AgentSkill(
        id="cash_flow",
        name="Cash-flow and affordability",
        description=(
            "Tests whether a recurring or one-off commitment is affordable "
            "against current income and savings."
        ),
        tags=["planning", "cash-flow"],
        examples=["Can I afford a $500/month car payment?"],
    ),
]


async def build_runner() -> Runner:
    """Build the ADK Runner for the planner.

    Module-level and async on purpose:

    * module-level so the deployed ``A2aAgent`` pickles this as a by-reference
      callable (a lambda would be serialized by value);
    * async so the MCP toolset's ``get_tools()`` can be awaited inside the
      running event loop. It cannot be awaited at import time, which is the
      same constraint ``app/fast_api_app.py`` solves in its FastAPI lifespan.
    """
    agent = build_financial_planner_agent()

    if os.getenv("MCP_REGISTRY_SERVER") or os.getenv("MCP_PORTFOLIO_URL"):
        # Replace the toolset placeholder with its concrete tools; the A2A
        # executor does not surface toolsets.
        from app.app_utils.api_registry_mcp import build_portfolio_mcp_toolset

        agent.tools = [t for t in agent.tools if not isinstance(t, BaseToolset)]
        agent.tools.extend(await build_portfolio_mcp_toolset().get_tools())
    else:
        logger.warning(
            "Neither MCP_REGISTRY_SERVER nor MCP_PORTFOLIO_URL is set - the "
            "planner will answer without live portfolio context."
        )

    return Runner(
        agent=agent,
        app_name=agent.name,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        memory_service=services.get_memory_service(),
        auto_create_session=True,
    )


def build_agent_executor() -> A2aAgentExecutor:
    """Executor factory. Module-level for the same pickling reason."""
    return A2aAgentExecutor(runner=build_runner)


a2a_agent = A2aAgent(
    agent_card=create_agent_card(
        agent_name="financial_planner",
        description=(
            "Goals-based financial planning: retirement readiness, savings "
            "targets, cash flow, and affordability projections."
        ),
        skills=_SKILLS,
    ),
    agent_executor_builder=build_agent_executor,
)
a2a_agent.set_up()
