"""Single-file entry point for ADK web UI discovery.

ADK's dev server (and the web UI's agent loader) expects this module to
expose ``root_agent``. The agent's own name remains ``financial_planner``
(used by the A2A routes); ``root_agent`` is the discovery alias.
"""

from app.agents.financial_planner_agent import financial_planner_agent

root_agent = financial_planner_agent

__all__ = ["root_agent"]
