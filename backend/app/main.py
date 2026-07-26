from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import Scope

from app.agents.graph import AnalysisAgent
from app.api.router import router
from app.config import get_settings
from app.connectors.client import DatasourceClient
from app.db import close_db, init_db
from app.llm.deepseek import DeepSeekClient
from app.runtime.events import EventBroker
from app.runtime.supervisor import AnalysisSupervisor

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
            return FileResponse(Path(self.directory) / "index.html")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    events = EventBroker()
    datasource_client = DatasourceClient(settings)
    llm = DeepSeekClient(settings)
    agent = AnalysisAgent(settings, datasource_client, llm, events)
    supervisor = AnalysisSupervisor(agent, settings.analysis_concurrency)
    app.state.events = events
    app.state.datasource_client = datasource_client
    app.state.supervisor = supervisor
    await supervisor.start()
    try:
        yield
    finally:
        await supervisor.stop()
        await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)

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
