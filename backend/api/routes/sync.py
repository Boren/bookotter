"""
Sync API routes.
Handles Hardcover and E-reader sync triggers.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel

from backend.clients.ereader_client import EreaderClient
from backend.clients.hardcover_client import HardcoverClient
from backend.config import get_ereader_by_id, get_first_real_ereader, load_config
from backend.database import SessionLocal
from backend.services.hardcover_sync_service import HardcoverSyncService
from backend.services.websocket_manager import manager as ws_manager
from backend.utils.pipeline_lock import get_active_lock

logger = logging.getLogger(__name__)

router = APIRouter()

# Guards against concurrent bulk E-reader syncs (manual clicks and the scheduled
# job). Manual triggers check-and-set on the event loop thread with no await in
# between, so two rapid clicks cannot both pass; the scheduled job runs in the
# APScheduler executor thread, where max_instances=1 prevents self-overlap.
# Cleared in the background task's finally (and the handler's error paths).
_ereader_sync_running = False

# APScheduler job id for the automatic E-reader sync (ereader_sync config section).
EREADER_SYNC_JOB_ID = "ereader_auto_sync"


def is_ereader_sync_running() -> bool:
    """Whether a bulk E-reader sync (manual or scheduled) is currently running.

    Consulted by PipelineService.kick_ereader_delivery so a per-book kick
    defers to an in-flight bulk sync instead of racing it over SSH.
    """
    return _ereader_sync_running


class EreaderSyncRequest(BaseModel):
    ereader_device: str
    dry_run: bool = False


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


def _run_ereader_sync_background(
    ereader_device: str,
    dry_run: bool = False,
    trigger_type: str = "manual",
) -> dict:
    # Plain def, NOT async: Starlette runs sync background tasks in the
    # threadpool, keeping the event loop free during long SFTP transfers.
    # broadcast_sync handles the worker-thread case via run_coroutine_threadsafe.
    # dry_run/trigger_type are passed by _run_scheduled_ereader_sync.
    global _ereader_sync_running
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
            # Refresh shelf statuses first so the mirror set reflects current
            # Hardcover state (matters for the nightly cron, which otherwise
            # mirrors whenever the last Hardcover sync happened to run). A
            # failed refresh leaves statuses untouched, which fails safe.
            hc_result = service.sync_hardcover_lists(db)
            if hc_result.get("errors"):
                logger.warning("Hardcover refresh before E-reader sync had errors: %s", hc_result)
            return service.run_ereader_sync(ereader_device, db, dry_run=dry_run)
        finally:
            db.close()
    except Exception as exc:
        logger.error("E-reader sync failed: %s", exc)
        ws_manager.broadcast_sync("ereader_sync_failed", {"error": str(exc)})
        return {"error": str(exc)}
    finally:
        _ereader_sync_running = False


def _run_scheduled_ereader_sync() -> dict:
    """APScheduler entry point for the automatic E-reader sync.

    Skips cheaply (log + return, no SSH) when no real E-reader is configured,
    a sync is already in flight, or the device fails the TCP probe — an
    offline E-reader just means the next tick tries again.
    """
    global _ereader_sync_running

    ereader = get_first_real_ereader()
    if ereader is None:
        logger.debug("Scheduled E-reader sync: no E-reader configured, skipping")
        return {"skipped": "no_ereader"}

    if _ereader_sync_running:
        logger.info("Scheduled E-reader sync: a sync is already in progress, skipping")
        return {"skipped": "already_running"}
    _ereader_sync_running = True

    try:
        client = EreaderClient.from_config(ereader)
        if not client.is_reachable():
            logger.info(
                "Scheduled E-reader sync: E-reader '%s' is offline, skipping until next run",
                ereader.get("name") or ereader.get("id"),
            )
            _ereader_sync_running = False
            return {"skipped": "ereader_offline"}
    except BaseException:
        _ereader_sync_running = False
        raise

    dry_run = load_config().get("transfer", {}).get("dry_run", False)
    # _run_ereader_sync_background's finally clears the running flag.
    return _run_ereader_sync_background(
        ereader_device=ereader["id"],
        dry_run=dry_run,
        trigger_type="scheduled",
    )


def apply_ereader_sync_schedule(config: dict | None = None) -> None:
    """Register, update, or remove the automatic E-reader sync job per config.

    Called at startup and whenever the ereader_sync config section is saved,
    so toggling the setting takes effect without a restart. Re-saving while
    enabled re-arms the interval (next run = now + interval); acceptable.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    from backend.services.scheduler_service import scheduler

    if config is None:
        config = load_config()
    ereader_sync = config.get("ereader_sync", {})

    if not ereader_sync.get("enabled"):
        scheduler.remove_job(EREADER_SYNC_JOB_ID)
        logger.info("Automatic E-reader sync disabled")
        return

    hours = ereader_sync.get("interval_hours", 1)
    if hours not in (1, 6, 24):
        logger.warning("Invalid ereader_sync.interval_hours=%r, falling back to 1", hours)
        hours = 1

    scheduler.scheduler.add_job(
        _run_scheduled_ereader_sync,
        trigger=IntervalTrigger(hours=hours),
        id=EREADER_SYNC_JOB_ID,
        name="Automatic E-reader sync",
        replace_existing=True,
    )
    logger.info("Automatic E-reader sync registered (every %d hour(s))", hours)


@router.post("/hardcover")
async def trigger_hardcover_sync(request: Request, background_tasks: BackgroundTasks):
    """Manually trigger Hardcover list sync."""
    background_tasks.add_task(_run_hardcover_sync_background, app=request.app)
    return {"success": True, "message": "Hardcover sync started"}


@router.post("/ereader")
async def trigger_ereader_sync(body: EreaderSyncRequest, background_tasks: BackgroundTasks):
    """Manually trigger E-reader sync for library books.

    Fails fast: probes the E-reader over TCP first (~3s worst case) so the user
    immediately learns the device is offline instead of a sync silently dying
    in the background. 409 if a manual sync is already running.
    """
    global _ereader_sync_running

    ereader_config = get_ereader_by_id(body.ereader_device)
    if not ereader_config:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ereader_not_found",
                "message": f"E-reader device '{body.ereader_device}' not found",
            },
        )

    if _ereader_sync_running:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ereader_sync_already_running",
                "message": "A E-reader sync is already in progress",
            },
        )
    _ereader_sync_running = True

    try:
        client = EreaderClient.from_config(ereader_config)
        reachable = await asyncio.to_thread(client.is_reachable)
        if not reachable:
            name = ereader_config.get("name") or body.ereader_device
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "ereader_offline",
                    "message": (
                        f"E-reader '{name}' is offline ({ereader_config.get('hostname', '')}) — "
                        "turn it on and connect to WiFi, then retry"
                    ),
                },
            )
    except BaseException:
        _ereader_sync_running = False
        raise

    dry_run = body.dry_run or load_config().get("transfer", {}).get("dry_run", False)
    if dry_run:
        # No transfers or deletions happen, so a dry run finishes in seconds —
        # run it synchronously and hand the caller the preview payload directly.
        result = await asyncio.to_thread(_run_ereader_sync_background, ereader_device=body.ereader_device, dry_run=True)
        return {"success": "error" not in result, **result}

    background_tasks.add_task(_run_ereader_sync_background, ereader_device=body.ereader_device)
    return {"success": True, "message": f"E-reader sync started for device '{body.ereader_device}'"}


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
