"""Wanted/missing queue API routes."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models.book import Book, BookStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/missing")
async def list_missing_books(db: Session = Depends(get_db)):
    """List all books currently missing from the library."""
    books = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.status == BookStatus.MISSING.value)
        .order_by(Book.updated_at.desc())
        .all()
    )
    return {"books": [book.to_dict() for book in books], "total": len(books)}


@router.post("/search-all")
async def search_all_missing(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Search-and-grab every WANTED/MISSING book asynchronously; progress streams via WebSocket."""
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline not configured (check Prowlarr and qBittorrent settings)",
        )

    pending = db.query(Book).filter(Book.status.in_([BookStatus.WANTED.value, BookStatus.MISSING.value])).count()

    if pending == 0:
        return {"queued": 0, "message": "No WANTED or MISSING books to search"}

    background_tasks.add_task(pipeline.process_wanted_books)
    logger.info(f"Queued bulk search for {pending} WANTED/MISSING book(s)")

    return {"queued": pending, "message": f"Searching {pending} book(s) in background"}
