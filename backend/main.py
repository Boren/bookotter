"""
BookOtter Web API - FastAPI application entry point.

Provides REST API and WebSocket endpoints for the BookOtter web interface.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import __app_name__, __version__
from backend.api.routes import (
    blocklist,
    browse,
    config,
    downloads,
    kindles,
    library,
    logs,
    root_folders,
    rss,
    scanner,
    schedules,
    search,
    services,
    sync,
    wanted,
)
from backend.config import DATA_DIR, load_config
from backend.database import init_db
from backend.services.scheduler_service import scheduler
from backend.services.websocket_manager import manager as ws_manager

logger = logging.getLogger(__name__)


def validate_config(cfg: dict) -> list[str]:
    """
    Validate required configuration fields.

    Returns a list of fatal error messages. If the list is non-empty, startup should abort.
    Warnings (e.g., missing kindle hostname) are logged but not returned.
    """
    errors = []

    # Hardcover API token (required)
    hc_token = cfg.get("hardcover", {}).get("api_token", "").strip()
    if not hc_token:
        errors.append("hardcover.api_token is required and must be non-empty")

    # Prowlarr API key (required)
    prowlarr_key = cfg.get("prowlarr", {}).get("api_key", "").strip()
    if not prowlarr_key:
        errors.append("prowlarr.api_key is required and must be non-empty")

    # Prowlarr base_url (required, must be valid URL)
    prowlarr_url = cfg.get("prowlarr", {}).get("base_url", "").strip()
    if not prowlarr_url:
        errors.append("prowlarr.base_url is required and must be non-empty")
    elif not (prowlarr_url.startswith("http://") or prowlarr_url.startswith("https://")):
        errors.append(f"prowlarr.base_url must start with http:// or https://, got: {prowlarr_url}")

    # qBittorrent password (required)
    qbt_password = cfg.get("qbittorrent", {}).get("password", "").strip()
    if not qbt_password:
        errors.append("qbittorrent.password is required and must be non-empty")

    # qBittorrent base_url (required, must be valid URL)
    qbt_url = cfg.get("qbittorrent", {}).get("base_url", "").strip()
    if not qbt_url:
        errors.append("qbittorrent.base_url is required and must be non-empty")
    elif not (qbt_url.startswith("http://") or qbt_url.startswith("https://")):
        errors.append(f"qbittorrent.base_url must start with http:// or https://, got: {qbt_url}")

    # Kindles: warn if any has empty hostname (non-fatal)
    kindles = cfg.get("kindles", [])
    for i, kindle in enumerate(kindles):
        hostname = kindle.get("hostname", "").strip()
        if not hostname:
            logger.warning(f"kindles[{i}] has empty hostname — Kindle sync will fail for this device")

    return errors


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
    log_file = setup_logging()
    logger.info("Initializing BookOtter...")
    logger.info(f"Logging initialized, writing to {log_file}")

    ws_manager.set_loop(asyncio.get_running_loop())

    init_db()
    logger.info("Database initialized")

    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started")

    pipeline = None
    app_config = load_config()

    # Validate configuration
    config_errors = validate_config(app_config)
    if config_errors:
        for err in config_errors:
            logger.error("Config validation error: %s", err)
        raise RuntimeError("Configuration invalid; see log for details")

    try:
        prowlarr_config = app_config.get("prowlarr", {})
        qbt_config = app_config.get("qbittorrent", {})

        if prowlarr_config.get("api_key") and qbt_config.get("password"):
            from backend.clients.prowlarr_client import ProwlarrClient
            from backend.clients.qbittorrent_client import QBittorrentClient
            from backend.database import SessionLocal
            from backend.services.download_service import DownloadService
            from backend.services.epub_service import EpubService
            from backend.services.import_service import ImportService
            from backend.services.pipeline_service import PipelineService
            from backend.services.search_service import SearchService

            prowlarr = ProwlarrClient(
                api_key=prowlarr_config["api_key"],
                base_url=prowlarr_config.get("base_url", "http://localhost:9696"),
            )
            qbt = QBittorrentClient(
                username=qbt_config.get("username", "admin"),
                password=qbt_config["password"],
                base_url=qbt_config.get("base_url", "http://localhost:8080"),
            )
            epub_service = EpubService()
            search_service = SearchService(prowlarr)
            download_service = DownloadService(
                qbt,
                SessionLocal,
                category=qbt_config.get("category", "books"),
                ws_manager=ws_manager,
            )
            import_service = ImportService(db=SessionLocal(), epub_service=epub_service, ws_manager=ws_manager)

            pipeline = PipelineService(
                search_service=search_service,
                download_service=download_service,
                import_service=import_service,
                ws_manager=ws_manager,
            )
            pipeline.start_monitoring()
            app.state.pipeline = pipeline
            logger.info("Pipeline monitoring started")

            # Reconcile download states with qBittorrent
            try:
                download_service.reconcile_on_startup()
                logger.info("Download reconciliation completed on startup")
            except Exception as e:
                logger.error(f"Download reconciliation failed on startup: {e}")

            try:
                from backend.services.rss_sync_service import RssSyncService

                rss_service = RssSyncService(
                    prowlarr_client=prowlarr,
                    search_service=search_service,
                    pipeline_service=pipeline,
                    ws_manager=ws_manager,
                    db_session_factory=SessionLocal,
                )
                app.state.rss_service = rss_service
                logger.info("RSS sync service initialized")

                rss_config = app_config.get("rss", {})
                if rss_config.get("enabled") is True:
                    try:
                        scheduler.add_rss_sync_job(
                            "rss_sync",
                            rss_config.get("cron_expression", "*/15 * * * *"),
                            lambda: rss_service.run_sync_cycle("scheduled"),
                        )
                    except Exception as e:
                        logger.error(f"Failed to register RSS sync job: {e}")
                else:
                    logger.info("RSS sync is disabled (rss.enabled=False)")

                # Cleanup runs even when rss.enabled=False, to drain old seen items
                try:
                    scheduler.add_rss_cleanup_job(
                        "rss_cleanup",
                        "0 3 * * *",
                        lambda: rss_service.cleanup_old_seen_items(),
                    )
                except Exception as e:
                    logger.error(f"Failed to register RSS cleanup job: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize RSS sync service: {e}")
        else:
            logger.info("Pipeline not started: Prowlarr/qBittorrent not fully configured")
    except Exception as e:
        logger.error(f"Failed to start pipeline monitoring: {e}")

    try:
        hc_config = app_config.get("hardcover", {})
        if hc_config.get("api_token"):
            from apscheduler.triggers.interval import IntervalTrigger

            from backend.clients.hardcover_client import HardcoverClient
            from backend.database import SessionLocal
            from backend.services.hardcover_sync_service import HardcoverSyncService

            def _scheduled_hardcover_sync():
                config = load_config()
                client = HardcoverClient(
                    api_token=config["hardcover"]["api_token"],
                    api_url=config["hardcover"].get("api_url", "https://api.hardcover.app/v1/graphql"),
                )
                service = HardcoverSyncService(hardcover_client=client, config=config)
                db = SessionLocal()
                try:
                    result = service.sync_hardcover_lists(db)
                    logger.info(f"Scheduled Hardcover sync result: {result}")
                finally:
                    db.close()

                pipeline_config = config.get("pipeline", {})
                search_on_add = pipeline_config.get("search_on_add", True)
                new_books = result.get("new_books", 0)
                pipeline_svc = getattr(app.state, "pipeline", None)
                if search_on_add and new_books > 0 and pipeline_svc is not None:
                    try:
                        grabbed = pipeline_svc.process_wanted_books()
                        logger.info(
                            "Auto-search after scheduled Hardcover sync: grabbed %d/%d new books",
                            grabbed,
                            new_books,
                        )
                    except Exception as exc:
                        logger.error("Auto-search after scheduled Hardcover sync failed: %s", exc)

            scheduler.scheduler.add_job(
                _scheduled_hardcover_sync,
                trigger=IntervalTrigger(minutes=30),
                id="hardcover_poller",
                name="Hardcover list poller",
                replace_existing=True,
            )
            logger.info("Hardcover poller registered (every 30 minutes)")
        else:
            logger.info("Hardcover poller not started: API token not configured")
    except Exception as e:
        logger.error(f"Failed to register Hardcover poller: {e}")

    yield

    if pipeline:
        pipeline.stop_monitoring()
        logger.info("Pipeline monitoring stopped")

    scheduler.shutdown()
    logger.info("Scheduler stopped")


# Create FastAPI app
app = FastAPI(
    title=__app_name__,
    description="Sync books from Hardcover reading lists to Kindle",
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
app.include_router(services.router, prefix="/api", tags=["services"])
app.include_router(browse.router, prefix="/api/browse", tags=["browse"])
app.include_router(kindles.router, prefix="/api/kindles", tags=["kindles"])
app.include_router(root_folders.router, prefix="/api/root-folders", tags=["root-folders"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(wanted.router, prefix="/api/wanted", tags=["wanted"])
app.include_router(blocklist.router, prefix="/api/blocklist", tags=["blocklist"])
app.include_router(rss.router, prefix="/api/rss", tags=["rss"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(scanner.router)


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
