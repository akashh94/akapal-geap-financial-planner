"""Financial Planning / Wealth Advisor agent (ADK)."""

import logging
import os

from google.adk.agents import LlmAgent
from google.adk.tools import BaseTool, FunctionTool, load_memory, preload_memory
from google.adk.tools.base_toolset import BaseToolset

from app.app_utils.api_registry_mcp import build_portfolio_mcp_toolset
from app.app_utils.memory_callbacks import save_session_to_memory_callback
from app.config.models import build_model
from app.prompts.planner_prompt import PLANNER_PROMPT
from app.tools import planning_calculator

logger = logging.getLogger(__name__)

_calc_tools = [
    FunctionTool(planning_calculator.future_value),
    FunctionTool(planning_calculator.present_value),
    FunctionTool(planning_calculator.payment),
    FunctionTool(planning_calculator.n_periods),
    FunctionTool(planning_calculator.retirement_projection),
    FunctionTool(planning_calculator.savings_goal_projection),
]


def build_financial_planner_agent() -> LlmAgent:
    """Build the planner agent with calculators and the portfolio MCP toolset.

    The MCP toolset's ``get_tools()`` is async and must be awaited inside a
    running event loop — not at module import (``asyncio.run()`` fails when a
    loop is already running, e.g. FastAPI startup). The toolset is included
    as-is here; the FastAPI lifespan flattens it into concrete tools for the
    A2A executor, which does not surface toolsets.
    """
    tools: list[BaseTool | BaseToolset] = list(_calc_tools)
    if os.getenv("MCP_REGISTRY_SERVER") or os.getenv("MCP_PORTFOLIO_URL"):
        tools.append(build_portfolio_mcp_toolset())
    else:
        logger.warning(
            "Neither MCP_REGISTRY_SERVER nor MCP_PORTFOLIO_URL is set — "
            "portfolio data tools are disabled. The planner will answer "
            "without live portfolio context."
        )

    return LlmAgent(
        name="financial_planner",
        model=build_model(),
        description=(
            "Goals-based financial planning: retirement readiness, savings targets, "
            "cash-flow, and affordability projections."
        ),
        instruction=PLANNER_PROMPT,
        tools=tools + [preload_memory, load_memory],
        after_agent_callback=save_session_to_memory_callback,
    )


financial_planner_agent = build_financial_planner_agent()
