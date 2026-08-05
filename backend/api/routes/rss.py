"""
RSS API routes.
Exposes status and manual-trigger endpoints for the Prowlarr RSS sync service.
"""

import logging
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import load_config
from backend.database import get_db
from backend.models.rss import RssIndexerState

logger = logging.getLogger(__name__)

router = APIRouter()


class RssIndexerStateResponse(BaseModel):
    """Per-indexer RSS state, serialized with camelCase keys for the frontend."""

    indexer_id: int = Field(serialization_alias="indexerId")
    indexer_name: str | None = Field(default=None, serialization_alias="indexerName")
    last_poll_at: datetime | None = Field(default=None, serialization_alias="lastPollAt")
    last_status: str | None = Field(default=None, serialization_alias="lastStatus")
    last_error: str | None = Field(default=None, serialization_alias="lastError")
    items_seen_count: int = Field(default=0, serialization_alias="itemsSeenCount")
    items_grabbed_count: int = Field(default=0, serialization_alias="itemsGrabbedCount")
    retry_not_before_at: datetime | None = Field(default=None, serialization_alias="retryNotBeforeAt")
    caps_cached_at: datetime | None = Field(default=None, serialization_alias="capsCachedAt")
    caps_supports_book_search: bool | None = Field(default=None, serialization_alias="capsSupportsBookSearch")

    @classmethod
    def from_orm_state(cls, state: RssIndexerState) -> RssIndexerStateResponse:
        state_row = cast(Any, state)
        return cls(
            indexer_id=int(state_row.indexer_id),
            indexer_name=state_row.indexer_name,
            last_poll_at=state_row.last_poll_at,
            last_status=state_row.last_status,
            last_error=state_row.last_error,
            items_seen_count=int(state_row.items_seen_count or 0),
            items_grabbed_count=int(state_row.items_grabbed_count or 0),
            retry_not_before_at=state_row.retry_not_before_at,
            caps_cached_at=state_row.caps_cached_at,
            caps_supports_book_search=state_row.caps_supports_book_search,
        )


class RssStatusResponse(BaseModel):
    """Top-level RSS status response shape consumed by the frontend store."""

    enabled: bool
    sync_in_progress: bool = Field(serialization_alias="syncInProgress")
    last_sync_started_at: str | None = Field(default=None, serialization_alias="lastSyncStartedAt")
    last_sync_completed_at: str | None = Field(default=None, serialization_alias="lastSyncCompletedAt")
    indexers: list[RssIndexerStateResponse] = Field(default_factory=list)
    recent_matches: list[dict[str, Any]] = Field(default_factory=list, serialization_alias="recentMatches")


@router.get("/status")
async def get_rss_status(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Return the current RSS sync state for the dashboard."""
    rss_service = getattr(request.app.state, "rss_service", None)
    sync_in_progress = bool(rss_service.is_sync_in_progress()) if rss_service is not None else False
    last_sync_started_at = getattr(rss_service, "_last_sync_started_at", None)
    last_sync_completed_at = getattr(rss_service, "_last_sync_completed_at", None)
    recent_matches = getattr(rss_service, "_recent_matches", [])

    config = load_config()
    enabled = bool(config.get("rss", {}).get("enabled", False))

    indexer_rows = db.query(RssIndexerState).order_by(RssIndexerState.indexer_id).all()
    indexers = [RssIndexerStateResponse.from_orm_state(row) for row in indexer_rows]

    response = RssStatusResponse(
        enabled=enabled,
        sync_in_progress=sync_in_progress,
        last_sync_started_at=last_sync_started_at,
        last_sync_completed_at=last_sync_completed_at,
        indexers=indexers,
        recent_matches=list(recent_matches),
    )
    return JSONResponse(content=response.model_dump(mode="json", by_alias=True))


@router.post("/sync")
async def trigger_rss_sync(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Manually trigger an RSS sync cycle. Returns 409 if a sync is already running."""
    rss_service = getattr(request.app.state, "rss_service", None)
    if rss_service is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": "rss_service_not_initialized"},
        )

    if rss_service.is_sync_in_progress():
        return JSONResponse(
            status_code=409,
            content={"status": "in_progress", "reason": "sync_in_progress"},
        )

    background_tasks.add_task(rss_service.run_sync_cycle, "manual")
    return JSONResponse(status_code=200, content={"status": "started"})
