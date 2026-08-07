"""Financial Planning / Wealth Advisor agent (ADK)."""

import logging
import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams

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

_tools = list(_calc_tools)
if mcp_url := os.getenv("MCP_PORTFOLIO_URL"):
    _tools.append(
        McpToolset(
            connection_params=SseConnectionParams(
                url=mcp_url,
                timeout=10.0,
            ),
        )
    )
else:
    logger.warning(
        "MCP_PORTFOLIO_URL is not set — portfolio data tools are disabled. "
        "The planner will answer without live portfolio context."
    )

financial_planner_agent = LlmAgent(
    name="financial_planner",
    model=build_model(),
    description=(
        "Goals-based financial planning: retirement readiness, savings targets, "
        "cash-flow, and affordability projections."
    ),
    instruction=PLANNER_PROMPT,
    tools=_tools,
)
