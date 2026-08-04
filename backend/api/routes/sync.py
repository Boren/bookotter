"""
Sync API routes.
Handles Hardcover and Kindle sync triggers.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel

from backend.clients.hardcover_client import HardcoverClient
from backend.clients.kindle_client import KindleClient
from backend.config import get_kindle_by_id, load_config
from backend.database import SessionLocal
from backend.services.hardcover_sync_service import HardcoverSyncService
from backend.services.websocket_manager import manager as ws_manager
from backend.utils.pipeline_lock import get_active_lock

logger = logging.getLogger(__name__)

router = APIRouter()

# Guards against concurrent manual Kindle syncs. Checked and set on the event
# loop thread with no await in between, so two rapid clicks cannot both pass;
# cleared in the background task's finally (and the handler's error paths).
_kindle_sync_running = False


class KindleSyncRequest(BaseModel):
    kindle_device: str


@router.get("/status")
async def get_sync_status():
    """Get current sync status."""
    return {
        "is_running": False,
        "latest_run": None,
        "websocket_clients": ws_manager.connection_count,
    }


def _run_hardcover_sync_background(app: FastAPI | None = None) -> dict:
    config = load_config()
    hc_config = config.get("hardcover", {})
    api_token = hc_config.get("api_token", "")
    api_url = hc_config.get("api_url", "https://api.hardcover.app/v1/graphql")

    if not api_token:
        logger.error("Hardcover API token not configured")
        return {"error": "Hardcover API token not configured"}

    client = HardcoverClient(api_token=api_token, api_url=api_url)
    service = HardcoverSyncService(hardcover_client=client, config=config)

    db = SessionLocal()
    try:
        result = service.sync_hardcover_lists(db)
    finally:
        db.close()

    pipeline_config = config.get("pipeline", {})
    search_on_add = pipeline_config.get("search_on_add", True)
    new_books = result.get("new_books", 0)

    if search_on_add and new_books > 0 and app is not None:
        pipeline = getattr(app.state, "pipeline", None)
        if pipeline is not None:
            try:
                grabbed = 0
                for book_id in result.get("new_book_ids", []):
                    grabbed += pipeline.search_single_book(book_id)
                logger.info(
                    "Auto-search after Hardcover sync: grabbed %d/%d new books",
                    grabbed,
                    new_books,
                )
                result["auto_searched"] = grabbed
            except Exception as exc:
                logger.error("Auto-search after Hardcover sync failed: %s", exc)
                result["auto_search_error"] = str(exc)
        else:
            logger.warning(
                "search_on_add=true but pipeline service is not initialized — skipping auto-search for %d new book(s)",
                new_books,
            )

    return result


def _run_kindle_sync_background(
    kindle_device: str,
    dry_run: bool = False,
    trigger_type: str = "manual",
) -> dict:
    # Plain def, NOT async: Starlette runs sync background tasks in the
    # threadpool, keeping the event loop free during long SFTP transfers.
    # broadcast_sync handles the worker-thread case via run_coroutine_threadsafe.
    # dry_run/trigger_type are passed by the scheduler (add_sync_job kwargs);
    # dry_run is not implemented — a scheduled dry run performs a real sync.
    global _kindle_sync_running
    if dry_run:
        logger.warning("Kindle sync dry_run requested but not implemented — running a real sync")
    try:
        config = load_config()
        hc_config = config.get("hardcover", {})
        api_token = hc_config.get("api_token", "")
        api_url = hc_config.get("api_url", "https://api.hardcover.app/v1/graphql")

        client = HardcoverClient(api_token=api_token, api_url=api_url)
        service = HardcoverSyncService(
            hardcover_client=client,
            config=config,
            emit_callback=ws_manager.broadcast_sync,
        )

        db = SessionLocal()
        try:
            return service.run_kindle_sync(kindle_device, db)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Kindle sync failed: %s", exc)
        ws_manager.broadcast_sync("kindle_sync_failed", {"error": str(exc)})
        return {"error": str(exc)}
    finally:
        _kindle_sync_running = False


@router.post("/hardcover")
async def trigger_hardcover_sync(request: Request, background_tasks: BackgroundTasks):
    """Manually trigger Hardcover list sync."""
    background_tasks.add_task(_run_hardcover_sync_background, app=request.app)
    return {"success": True, "message": "Hardcover sync started"}


@router.post("/kindle")
async def trigger_kindle_sync(body: KindleSyncRequest, background_tasks: BackgroundTasks):
    """Manually trigger Kindle sync for library books.

    Fails fast: probes the Kindle over TCP first (~3s worst case) so the user
    immediately learns the device is offline instead of a sync silently dying
    in the background. 409 if a manual sync is already running.
    """
    global _kindle_sync_running

    kindle_config = get_kindle_by_id(body.kindle_device)
    if not kindle_config:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "kindle_not_found",
                "message": f"Kindle device '{body.kindle_device}' not found",
            },
        )

    if _kindle_sync_running:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "kindle_sync_already_running",
                "message": "A Kindle sync is already in progress",
            },
        )
    _kindle_sync_running = True

    try:
        client = KindleClient.from_config(kindle_config)
        reachable = await asyncio.to_thread(client.is_reachable)
        if not reachable:
            name = kindle_config.get("name") or body.kindle_device
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "kindle_offline",
                    "message": (
                        f"Kindle '{name}' is offline ({kindle_config.get('hostname', '')}) — "
                        "turn it on and connect to WiFi, then retry"
                    ),
                },
            )
    except BaseException:
        _kindle_sync_running = False
        raise

    background_tasks.add_task(_run_kindle_sync_background, kindle_device=body.kindle_device)
    return {"success": True, "message": f"Kindle sync started for device '{body.kindle_device}'"}


@router.post("/pipeline")
async def trigger_pipeline(request: Request):
    """
    Manually trigger a pipeline run (post-grab stages: grabbed → downloading → importing).

    Returns 409 with the active lock holder/run_id if a run is already in progress
    (e.g. the scheduled APScheduler job, or another concurrent manual trigger).
    """
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "pipeline_not_initialized"},
        )

    result = pipeline.run_pipeline(holder="manual")

    if result.get("skipped") and result.get("reason") == "lock_held":
        db = SessionLocal()
        try:
            active_lock = get_active_lock(db)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "pipeline_already_running",
                    "holder": active_lock.holder if active_lock is not None else "unknown",
                    "run_id": active_lock.run_id if active_lock is not None else None,
                },
            )
        finally:
            db.close()

    return {"success": True, "result": result}
