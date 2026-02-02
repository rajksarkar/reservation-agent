"""FastAPI application for the web dashboard."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from reservation_agent.api.routes import dashboard, reservations, restaurants
from reservation_agent.core.config import load_config
from reservation_agent.core.orchestrator import Orchestrator
from reservation_agent.db.models import init_database, get_session_factory
from reservation_agent.db.repository import Repository
from reservation_agent.utils.logging import setup_logging, get_logger

logger = get_logger(__name__)

# Global orchestrator reference (set during startup)
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator | None:
    """Get the global orchestrator instance."""
    return _orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _orchestrator

    # Load configuration
    config = load_config()
    setup_logging(config.log_level, config.log_dir)

    # Initialize database
    engine = await init_database(config.database_url)
    session_factory = get_session_factory(engine)
    app.state.repository = Repository(session_factory)

    # Initialize orchestrator (if not in API-only mode)
    if not getattr(app.state, "api_only", False):
        _orchestrator = Orchestrator(config)
        await _orchestrator.start()
        app.state.orchestrator = _orchestrator

    logger.info("application_started")

    yield

    # Shutdown
    if _orchestrator:
        await _orchestrator.stop()

    logger.info("application_stopped")


def create_app(api_only: bool = False) -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Reservation Agent",
        description="Autonomous restaurant reservation monitoring",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.api_only = api_only

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Set up templates
    templates_dir = Path(__file__).parent / "static" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    app.state.templates = Jinja2Templates(directory=templates_dir)

    # Include routers
    app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
    app.include_router(reservations.router, prefix="/api", tags=["reservations"])
    app.include_router(restaurants.router, prefix="/api", tags=["restaurants"])

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Serve the main dashboard."""
        return app.state.templates.TemplateResponse(
            "index.html", {"request": request}
        )

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    return app


# Default app instance
app = create_app()
