"""Shared model configuration for the Financial Planner agent."""

import os

from google.adk.models.google_llm import Gemini
from google.genai import types

DEFAULT_MODEL = "gemini-2.5-flash"

# POC projects have low default Vertex AI requests-per-minute quota, and a
# multi-agent turn fires several model calls in quick succession - 429
# RESOURCE_EXHAUSTED bursts are expected. Retry with exponential backoff
# instead of failing the turn.
_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=6,
    initial_delay=2.0,
    exp_base=2.0,
    http_status_codes=[429, 500, 503, 504],
)


def build_model() -> Gemini:
    """Return the Gemini model used by the planner.

    Reads AGENT_MODEL / MODEL_LOCATION from the environment at call time,
    so the deployed engine picks up values set via .env or the deployment
    environment. Model calls route to the "global" endpoint by default.
    """
    return Gemini(
        model=os.getenv("AGENT_MODEL", DEFAULT_MODEL),
        retry_options=_RETRY_OPTIONS,
        client_kwargs={
            "vertexai": True,
            "location": os.getenv("MODEL_LOCATION", "global"),
        },
    )
