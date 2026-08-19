"""Build the planner's MCP toolset for the portfolio data server.

Connects to the portfolio MCP server through the Google Cloud Agent Registry
when ``MCP_REGISTRY_SERVER`` is set, and falls back to a direct Streamable
HTTP connection (``MCP_PORTFOLIO_URL``) otherwise so local development keeps
working without a registry.

The registry provides discovery + auth: the registered server's endpoint URL
is resolved at runtime and an authorization header is attached automatically.
"""

from __future__ import annotations

import logging
import os

from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)

#: Default Streamable HTTP URL for local development (no registry).
_DEFAULT_LOCAL_MCP_URL = "https://mcp-portfolio-947331501288.us-central1.run.app/mcp"


def _build_registry_toolset() -> BaseToolset:
    """Build an ``McpToolset`` for the MCP server registered in Agent Registry.

    Reads the registry configuration from the environment:

    * ``MCP_REGISTRY_PROJECT_ID`` — project where the Agent Registry lives
      (defaults to ``GOOGLE_CLOUD_PROJECT`` if unset).
    * ``MCP_REGISTRY_LOCATION`` — location of the registry resource
      (defaults to ``global``).
    * ``MCP_REGISTRY_SERVER`` — full resource name of the registered MCP
      server, e.g.
      ``projects/<project>/locations/<location>/mcpServers/<name>``.
    """
    project_id = os.getenv(
        "MCP_REGISTRY_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "")
    )
    location = os.getenv("MCP_REGISTRY_LOCATION", "global")
    server_name = os.getenv("MCP_REGISTRY_SERVER", "")

    if not project_id or not location or not server_name:
        raise ValueError(
            "MCP_REGISTRY_PROJECT_ID, MCP_REGISTRY_LOCATION and "
            "MCP_REGISTRY_SERVER must be set when using the Agent Registry "
            "connection."
        )

    logger.info(
        "Connecting portfolio MCP via Agent Registry: project=%s location=%s server=%s",
        project_id,
        location,
        server_name,
    )
    registry = AgentRegistry(project_id=project_id, location=location)
    return registry.get_mcp_toolset(mcp_server_name=server_name)


def build_portfolio_mcp_toolset() -> BaseToolset:
    """Return a toolset for the portfolio MCP server.

    Uses the Agent Registry connection when ``MCP_REGISTRY_SERVER`` is set;
    otherwise falls back to the direct Streamable HTTP URL from
    ``MCP_PORTFOLIO_URL``.
    """
    if os.getenv("MCP_REGISTRY_SERVER"):
        return _build_registry_toolset()

    from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

    url = os.getenv("MCP_PORTFOLIO_URL", _DEFAULT_LOCAL_MCP_URL)
    logger.info("Connecting portfolio MCP via direct Streamable HTTP: %s", url)
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            timeout=10.0,
        ),
    )
