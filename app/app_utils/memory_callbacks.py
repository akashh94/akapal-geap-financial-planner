"""Shared ADK memory callbacks for the Financial Planner agent."""

from __future__ import annotations

from google.adk.agents.callback_context import CallbackContext


async def save_session_to_memory_callback(
    callback_context: CallbackContext,
) -> None:
    """Persist the agent's session to the Vertex AI Memory Bank after each turn."""
    await callback_context.add_session_to_memory()
    return None
