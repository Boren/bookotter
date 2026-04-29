"""
Sync API routes.
Handles Hardcover and Kindle sync triggers.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from backend.clients.hardcover_client import HardcoverClient
from backend.config import load_config
from backend.database import SessionLocal
from backend.services.hardcover_sync_service import HardcoverSyncService
from backend.services.websocket_manager import manager as ws_manager
from backend.utils.pipeline_lock import get_active_lock

logger = logging.getLogger(__name__)

router = APIRouter()


class KindleSyncRequest(BaseModel):
    kindle_device: str


async def emit_to_websocket(event: str, data: dict):
    """Emit sync events to connected WebSocket clients."""
    await ws_manager.broadcast(event, data)


@router.get("/status")
async def get_sync_status():
    """Get current sync status."""
    return {
        "is_running": False,
        "latest_run": None,
        "websocket_clients": ws_manager.connection_count,
    }


def _run_hardcover_sync_background() -> dict:
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
        return service.sync_hardcover_lists(db)
    finally:
        db.close()


async def _run_kindle_sync_background(kindle_device: str) -> dict:
    config = load_config()
    hc_config = config.get("hardcover", {})
    api_token = hc_config.get("api_token", "")
    api_url = hc_config.get("api_url", "https://api.hardcover.app/v1/graphql")

    client = HardcoverClient(api_token=api_token, api_url=api_url)
    service = HardcoverSyncService(
        hardcover_client=client,
        config=config,
        emit_callback=emit_to_websocket,
    )

    db = SessionLocal()
    try:
        return service.run_kindle_sync(kindle_device, db)
    finally:
        db.close()


@router.post("/hardcover")
async def trigger_hardcover_sync(background_tasks: BackgroundTasks):
    """Manually trigger Hardcover list sync."""
    background_tasks.add_task(_run_hardcover_sync_background)
    return {"success": True, "message": "Hardcover sync started"}


@router.post("/kindle")
async def trigger_kindle_sync(body: KindleSyncRequest, background_tasks: BackgroundTasks):
    """Manually trigger Kindle sync for library books."""
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
