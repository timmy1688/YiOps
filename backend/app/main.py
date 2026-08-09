from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import Scope

from app.agents.conversation import ConversationAgent
from app.agents.rca import RcaAgent
from app.api.control_plane import router as control_plane_router
from app.api.conversations import router as conversations_router
from app.api.demos import router as demos_router
from app.api.evaluations import router as evaluations_router
from app.api.investigations import router as investigations_router
from app.api.wiki import router as wiki_router
from app.config import get_settings
from app.db import close_db, init_db
from app.llm.gateway import ModelGateway
from app.mcp.client import MCPDatasourceGateway
from app.memory.wiki import WikiMemory
from app.runtime.events import EventBroker
from app.runtime.rca_supervisor import RcaSupervisor
from app.security.auth import AuthenticationMiddleware, ensure_bootstrap_identity
from app.security.auth import router as auth_router
from app.services.investigations import InvestigationRunner, InvestigationSupervisor

settings = get_settings()
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serve Vue assets and fall back to index.html for history-mode routes."""

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            # API typos or frontend/backend version mismatches must stay 404s.
            # Returning index.html here makes API clients treat HTML as JSON.
            if path == "api" or path.startswith("api/"):
                raise
            return FileResponse(Path(self.directory) / "index.html")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await ensure_bootstrap_identity(settings)
    events = EventBroker()
    datasource_gateway = MCPDatasourceGateway(settings)
    model_gateway = ModelGateway(settings)
    conversation_agent = ConversationAgent(settings, model_gateway)
    memory = WikiMemory(settings)
    rca_agent = RcaAgent(settings, datasource_gateway, model_gateway, events, memory)
    rca_supervisor = RcaSupervisor(rca_agent, settings.analysis_concurrency)
    investigation_runner = InvestigationRunner(
        datasource_gateway, conversation_agent, events, memory
    )
    investigation_supervisor = InvestigationSupervisor(
        investigation_runner, settings.analysis_concurrency
    )
    app.state.events = events
    app.state.datasource_gateway = datasource_gateway
    app.state.memory = memory
    app.state.conversation_agent = conversation_agent
    app.state.rca_supervisor = rca_supervisor
    app.state.investigation_supervisor = investigation_supervisor
    await rca_supervisor.start()
    await investigation_supervisor.start()
    try:
        yield
    finally:
        await investigation_supervisor.stop()
        await rca_supervisor.stop()
        await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthenticationMiddleware, settings=settings)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(control_plane_router, prefix=settings.api_prefix)
app.include_router(conversations_router, prefix=settings.api_prefix)
app.include_router(investigations_router, prefix=settings.api_prefix)
app.include_router(wiki_router, prefix=settings.api_prefix)
app.include_router(evaluations_router, prefix=settings.api_prefix)
app.include_router(demos_router, prefix=settings.api_prefix)

if frontend_dist.is_dir():
    app.mount(
        "/",
        SPAStaticFiles(directory=frontend_dist, html=True),
        name="frontend",
    )
else:

    @app.get("/", include_in_schema=False)
    async def frontend_not_built() -> dict[str, str]:
        return {
            "message": "YiOps frontend is not built. Run ./service.sh start.",
            "docs": "/docs",
        }
