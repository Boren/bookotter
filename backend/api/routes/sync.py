"""
Sync API routes.
Handles sync operations: start, stop, status, and history.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.sync_run import BookResult, SyncRun
from backend.services.sync_service import is_sync_running, start_sync, stop_sync
from backend.services.websocket_manager import manager as ws_manager

router = APIRouter()


class SyncStartRequest(BaseModel):
    """Request body for starting a sync."""

    kindle_device: str | None = None
    dry_run: bool = False


async def emit_to_websocket(event: str, data: dict):
    """Emit sync events to connected WebSocket clients."""
    await ws_manager.broadcast(event, data)


async def run_sync_background(
    kindle_device: str | None,
    dry_run: bool,
):
    """Background task to run sync with WebSocket events."""
    try:
        await start_sync(
            kindle_device=kindle_device,
            dry_run=dry_run,
            trigger_type="manual",
            event_callback=emit_to_websocket,
        )
    except Exception as e:
        await ws_manager.broadcast("sync_error", {"error": str(e)})


@router.post("/start")
async def start_sync_endpoint(
    body: SyncStartRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a new sync operation.

    The sync runs in the background and emits progress via WebSocket.
    Status IDs are read from global config settings.
    """
    if is_sync_running():
        raise HTTPException(status_code=409, detail="A sync is already in progress")

    # Start sync in background
    background_tasks.add_task(
        run_sync_background,
        kindle_device=body.kindle_device,
        dry_run=body.dry_run,
    )

    return {
        "success": True,
        "message": "Sync started",
        "dry_run": body.dry_run,
    }


@router.post("/stop")
async def stop_sync_endpoint():
    """Cancel the currently running sync."""
    if await stop_sync():
        return {"success": True, "message": "Sync cancellation requested"}
    else:
        return {"success": False, "message": "No sync is running"}


@router.get("/status")
async def get_sync_status(db: Session = Depends(get_db)):
    """
    Get current sync status.

    Returns whether a sync is running and the latest run details.
    """
    is_running = is_sync_running()

    # Get latest sync run
    latest_run = db.query(SyncRun).order_by(SyncRun.started_at.desc()).first()

    return {
        "is_running": is_running,
        "latest_run": latest_run.to_dict() if latest_run else None,
        "websocket_clients": ws_manager.connection_count,
    }


@router.get("/runs")
async def list_sync_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List sync run history.

    Args:
        limit: Maximum number of runs to return
        offset: Number of runs to skip
    """
    total = db.query(SyncRun).count()

    runs = db.query(SyncRun).order_by(SyncRun.started_at.desc()).offset(offset).limit(limit).all()

    return {
        "runs": [r.to_dict() for r in runs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
async def get_sync_run(run_id: int, db: Session = Depends(get_db)):
    """Get details of a specific sync run."""
    run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")

    return run.to_dict()


@router.get("/runs/{run_id}/books")
async def get_sync_run_books(
    run_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Get book results for a specific sync run.

    Args:
        run_id: Sync run ID
        limit: Maximum number of books to return
        offset: Number of books to skip
        status: Filter by status (transferred, skipped, not_found, failed)
    """
    run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")

    query = db.query(BookResult).filter(BookResult.sync_run_id == run_id)

    if status:
        query = query.filter(BookResult.status == status)

    total = query.count()

    books = query.order_by(BookResult.processed_at.desc()).offset(offset).limit(limit).all()

    return {
        "books": [b.to_dict() for b in books],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/runs/{run_id}")
async def delete_sync_run(run_id: int, db: Session = Depends(get_db)):
    """Delete a sync run and its book results."""
    run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")

    if run.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running sync")

    db.delete(run)
    db.commit()

    return {"success": True, "message": f"Sync run {run_id} deleted"}


@router.get("/stats")
async def get_sync_stats(db: Session = Depends(get_db)):
    """Get aggregate sync statistics."""
    from sqlalchemy import func

    # Total runs
    total_runs = db.query(SyncRun).count()

    # Successful runs
    successful_runs = db.query(SyncRun).filter(SyncRun.status == "completed").count()

    # Aggregate stats from all runs
    stats = db.query(
        func.sum(SyncRun.total_books).label("total_books"),
        func.sum(SyncRun.transferred).label("transferred"),
        func.sum(SyncRun.matched).label("matched"),
        func.sum(SyncRun.not_found).label("not_found"),
        func.sum(SyncRun.failed).label("failed"),
        func.sum(SyncRun.skipped).label("skipped"),
    ).first()

    # Last successful sync
    last_successful = (
        db.query(SyncRun).filter(SyncRun.status == "completed").order_by(SyncRun.completed_at.desc()).first()
    )

    return {
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "total_books_processed": stats.total_books or 0,
        "total_transferred": stats.transferred or 0,
        "total_matched": stats.matched or 0,
        "total_not_found": stats.not_found or 0,
        "total_failed": stats.failed or 0,
        "total_skipped": stats.skipped or 0,
        "last_successful_sync": last_successful.completed_at.isoformat() if last_successful else None,
    }


@router.get("/latest-changes")
async def get_latest_changes(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    Get the latest book transfers and removals.

    Returns books with status 'transferred' or 'removed' sorted by processed_at.
    Useful for showing recent activity on the dashboard.
    """
    books = (
        db.query(BookResult)
        .filter(BookResult.status.in_(["transferred", "removed"]))
        .order_by(BookResult.processed_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "books": [b.to_dict() for b in books],
        "total": len(books),
    }
