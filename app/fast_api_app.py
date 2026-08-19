import contextlib
import logging
import os
from collections.abc import AsyncIterator

import google.auth
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes

load_dotenv()

logger = logging.getLogger(__name__)

try:
    _, project_id = google.auth.default()
except Exception:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "unknown")

if project_id and project_id != "unknown":
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
    try:
        import vertexai

        vertexai.init(project=project_id)
    except Exception as exc:
        logger.warning("vertexai.init() failed — proceeding without it (%s)", exc)

allow_origin = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import financial_planner_agent

    runner = Runner(
        agent=financial_planner_agent,
        app_name=financial_planner_agent.name,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = financial_planner_agent.name
    await attach_a2a_routes(
        app,
        agent=financial_planner_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{financial_planner_agent.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    allow_origins=allow_origin,
    auto_create_session=True,
    lifespan=lifespan,
    gemini_enterprise_app_name="app",
)
app.title = "financial-planner"
app.description = "API for interacting with the Agent financial-planner"
