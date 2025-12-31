"""
BookOtter Web API - FastAPI application entry point.

Provides REST API and WebSocket endpoints for the BookOtter web interface.
"""

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import __app_name__, __version__
from backend.api.routes import config, kindles, logs, schedules, sync
from backend.config import DATA_DIR, load_config
from backend.database import init_db
from backend.services.scheduler_service import scheduler
from backend.services.websocket_manager import manager as ws_manager


def setup_logging():
    """Configure application logging with file and console handlers."""
    app_config = load_config()
    log_config = app_config.get("logging", {})

    log_level_str = log_config.get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    log_filename = log_config.get("log_file", "bookotter.log")
    log_file = Path(DATA_DIR) / log_filename

    # Ensure data directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers to avoid duplicates on reload
    root_logger.handlers.clear()

    # File handler with rotation (10MB max, keep 3 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(file_handler)

    # Console handler for Docker logs
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return log_file


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events - startup and shutdown."""
    # Startup
    print("Initializing BookOtter...")

    # Setup logging first
    log_file = setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized, writing to {log_file}")

    init_db()
    logger.info("Database initialized")

    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started")

    # Load schedules from config.yaml
    try:
        from backend.services.sync_service import run_scheduled_sync

        loaded = scheduler.load_schedules_from_config(run_scheduled_sync)
        logger.info(f"Loaded {loaded} schedule(s) from config.yaml")
    except Exception as e:
        logger.error(f"Failed to load schedules from config: {e}")

    yield

    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler stopped")


# Create FastAPI app
app = FastAPI(
    title=__app_name__,
    description="Sync books from Hardcover reading lists to Kindle via Readarr",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, set specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(kindles.router, prefix="/api/kindles", tags=["kindles"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "bookotter"}


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time sync updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for messages
            data = await websocket.receive_text()
            # Echo back or handle commands if needed
            await websocket.send_json({"event": "pong", "data": data})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# Static file serving for frontend (production)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/")
    async def serve_frontend():
        """Serve the Vue.js frontend."""
        return FileResponse(static_dir / "index.html")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA fallback - serve index.html for client-side routing."""
        # Check if it's an API route
        if full_path.startswith("api/"):
            return {"error": "Not found"}

        # Check if file exists in static
        file_path = static_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)

        # Fallback to index.html for SPA routing
        return FileResponse(static_dir / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6887)
