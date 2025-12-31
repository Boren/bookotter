"""
Schedule management API routes.
Handles CRUD operations for scheduled sync jobs stored in config.yaml.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import (
    add_schedule,
    delete_schedule,
    generate_schedule_id,
    get_schedule_by_id,
    get_schedules,
    update_schedule,
)
from backend.services.scheduler_service import SchedulerService, scheduler

router = APIRouter()


class ScheduleCreate(BaseModel):
    """Request body for creating a schedule."""

    name: str
    cron_expression: str
    kindle_device: str | None = None
    dry_run: bool = False


class ScheduleUpdate(BaseModel):
    """Request body for updating a schedule."""

    name: str | None = None
    cron_expression: str | None = None
    kindle_device: str | None = None
    dry_run: bool | None = None
    enabled: bool | None = None


def schedule_to_response(schedule: dict) -> dict:
    """Convert config schedule to API response format with computed next_run_at."""
    next_run = SchedulerService.get_next_run_time(schedule.get("cron_expression", ""))
    return {
        "id": schedule.get("id"),
        "name": schedule.get("name"),
        "cron_expression": schedule.get("cron_expression"),
        "enabled": schedule.get("enabled", True),
        "kindle_device": schedule.get("kindle_device"),
        "dry_run": schedule.get("dry_run", False),
        "next_run_at": next_run.isoformat() if next_run else None,
        # last_run_at could be derived from SyncRun history if needed
        "last_run_at": None,
    }


@router.get("")
async def list_schedules():
    """List all scheduled syncs."""
    schedules = get_schedules()
    return [schedule_to_response(s) for s in schedules]


@router.get("/next")
async def get_next_run():
    """Get the next scheduled run time across all schedules."""
    next_run = scheduler.get_next_run()
    return {
        "next_run": next_run.isoformat() if next_run else None,
        "jobs": scheduler.get_all_jobs(),
    }


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Get a specific schedule."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
    return schedule_to_response(schedule)


@router.post("")
async def create_schedule(body: ScheduleCreate):
    """Create a new scheduled sync."""
    # Validate cron expression
    next_run = SchedulerService.get_next_run_time(body.cron_expression)
    if next_run is None:
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    # Generate ID from name
    schedule_id = generate_schedule_id(body.name)

    schedule = {
        "id": schedule_id,
        "name": body.name,
        "cron_expression": body.cron_expression,
        "enabled": True,
        "kindle_device": body.kindle_device,
        "dry_run": body.dry_run,
    }

    try:
        add_schedule(schedule)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Register with scheduler
    try:
        from backend.services.sync_service import run_scheduled_sync

        scheduler.add_sync_job(
            job_id=f"schedule_{schedule_id}",
            cron_expression=body.cron_expression,
            sync_func=run_scheduled_sync,
            kindle_device=body.kindle_device,
            dry_run=body.dry_run,
        )
    except ImportError:
        pass  # Sync service not available

    return {"success": True, "schedule": schedule_to_response(schedule)}


@router.put("/{schedule_id}")
async def update_schedule_route(schedule_id: str, body: ScheduleUpdate):
    """Update a schedule."""
    # Validate cron expression if provided
    if body.cron_expression:
        next_run = SchedulerService.get_next_run_time(body.cron_expression)
        if next_run is None:
            raise HTTPException(status_code=400, detail="Invalid cron expression")

    updates = body.model_dump(exclude_unset=True)
    updated = update_schedule(schedule_id, updates)

    if not updated:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # Update scheduler job
    job_id = f"schedule_{schedule_id}"
    if updated.get("enabled", True):
        try:
            from backend.services.sync_service import run_scheduled_sync

            scheduler.add_sync_job(
                job_id=job_id,
                cron_expression=updated["cron_expression"],
                sync_func=run_scheduled_sync,
                kindle_device=updated.get("kindle_device"),
                dry_run=updated.get("dry_run", False),
            )
        except ImportError:
            pass
    else:
        scheduler.remove_job(job_id)

    return {"success": True, "schedule": schedule_to_response(updated)}


@router.delete("/{schedule_id}")
async def delete_schedule_route(schedule_id: str):
    """Delete a schedule."""
    # Remove from scheduler first
    scheduler.remove_job(f"schedule_{schedule_id}")

    # Delete from config
    if not delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    return {"success": True, "message": f"Schedule {schedule_id} deleted"}


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str):
    """Enable or disable a schedule."""
    schedule = get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    new_enabled = not schedule.get("enabled", True)
    updated = update_schedule(schedule_id, {"enabled": new_enabled})

    # Update scheduler
    job_id = f"schedule_{schedule_id}"
    if new_enabled:
        try:
            from backend.services.sync_service import run_scheduled_sync

            scheduler.add_sync_job(
                job_id=job_id,
                cron_expression=updated["cron_expression"],
                sync_func=run_scheduled_sync,
                kindle_device=updated.get("kindle_device"),
                dry_run=updated.get("dry_run", False),
            )
        except ImportError:
            pass
    else:
        scheduler.remove_job(job_id)

    return {
        "success": True,
        "enabled": new_enabled,
        "schedule": schedule_to_response(updated),
    }
