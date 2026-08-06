"""
Library API routes.
Handles book CRUD operations and browsing with filtering/pagination.
"""

import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.config import load_config
from backend.database import get_db
from backend.errors import FailureReason, PipelineError
from backend.models.book import Author, Book, BookStatus, EpubMetaState, KindleDeliveryStatus, RootFolder
from backend.services.epub_service import EpubMetadata, EpubService
from backend.services.rename_service import RenameService
from backend.utils.clock import naive_utcnow
from backend.utils.failure import _append_failure_history

logger = logging.getLogger(__name__)

router = APIRouter()


class BookCreateRequest(BaseModel):
    title: str
    author_name: str | None = None
    hardcover_id: str | None = None
    isbn: str | None = None
    description: str | None = None
    publisher: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    status: str = BookStatus.WANTED.value


class BookUpdateRequest(BaseModel):
    title: str | None = None
    author_name: str | None = None
    hardcover_id: str | None = None
    isbn: str | None = None
    description: str | None = None
    publisher: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    rating: float | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    status: str | None = None


def _resolve_author(db: Session, author_name: str | None) -> Author | None:
    if not author_name:
        return None
    author = db.query(Author).filter(Author.name == author_name).first()
    if not author:
        author = Author(name=author_name)
        db.add(author)
        db.flush()
    return author


@router.get("/books")
async def list_books(
    status: str | None = Query(default=None, description="Filter by book status"),
    kindle_delivery_status: str | None = Query(
        default=None,
        pattern="^(PENDING|IN_PROGRESS|DELIVERED|SKIPPED|NONE)$",
        description="Filter by Kindle delivery status; NONE matches books never queued",
    ),
    author: str | None = Query(default=None, description="Filter by author name (partial match)"),
    search: str | None = Query(default=None, description="Search title or author"),
    sort_by: str = Query(default="created_at", pattern="^(title|created_at|updated_at|status)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Book).options(joinedload(Book.author))

    if status:
        query = query.filter(Book.status == status)

    if kindle_delivery_status:
        if kindle_delivery_status == "NONE":
            query = query.filter(Book.kindle_delivery_status.is_(None))
        else:
            query = query.filter(Book.kindle_delivery_status == kindle_delivery_status)

    if author:
        query = query.join(Author).filter(Author.name.ilike(f"%{author}%"))

    if search:
        search_term = f"%{search}%"
        query = query.outerjoin(Author).filter((Book.title.ilike(search_term)) | (Author.name.ilike(search_term)))

    total = query.count()

    sort_column = getattr(Book, sort_by)
    if sort_order == "desc":
        sort_column = sort_column.desc()
    query = query.order_by(sort_column)

    books = query.offset(offset).limit(limit).all()

    return {
        "books": [b.to_dict() for b in books],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/authors")
async def list_authors(db: Session = Depends(get_db)):
    """List all authors with their book count."""
    authors = db.query(Author).all()
    return {
        "authors": [
            {
                "id": a.id,
                "name": a.name,
                "hardcover_id": a.hardcover_id,
                "book_count": len(a.books),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in authors
        ],
        "total": len(authors),
    }


@router.get("/stats")
async def get_library_stats(db: Session = Depends(get_db)):
    """Get library statistics: total books by status, author count, total size."""
    total_books = db.query(Book).count()

    status_counts = {}
    for status in BookStatus:
        count = db.query(Book).filter(Book.status == status.value).count()
        status_counts[status.value] = count

    author_count = db.query(Author).count()

    total_size = (
        db.query(func.sum(Book.file_size))
        .filter(Book.status == BookStatus.IN_LIBRARY.value, Book.file_size.isnot(None))
        .scalar()
        or 0
    )

    kindle_counts = {}
    for kstatus in KindleDeliveryStatus:
        kindle_counts[kstatus.value] = db.query(Book).filter(Book.kindle_delivery_status == kstatus.value).count()

    return {
        "total_books": total_books,
        "by_status": status_counts,
        "by_kindle_delivery_status": kindle_counts,
        "author_count": author_count,
        "total_size_bytes": total_size,
    }


@router.get("/dlq")
def get_dlq(db: Session = Depends(get_db)):
    """Return dead-letter queue: permanent failures + recent failures."""
    from backend.services.dlq import get_permanent_failed, get_recent_failures

    permanent = get_permanent_failed(db)
    recent = get_recent_failures(db)

    return {
        "permanent_failed": [b.to_dict() for b in permanent],
        "recent_failures": [b.to_dict() for b in recent],
        "counts": {
            "permanent_failed": len(permanent),
            "recent_failures": len(recent),
        },
    }


@router.get("/books/{book_id}")
async def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
    return book.to_dict()


@router.get("/books/{book_id}/download")
async def download_book(book_id: int, db: Session = Depends(get_db)):
    """Serve a book's EPUB as a browser download."""
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    if not book.file_path or book.root_folder_id is None:
        raise HTTPException(status_code=404, detail="Book has no library file")

    root_folder = db.query(RootFolder).filter(RootFolder.id == book.root_folder_id).first()
    if root_folder is None:
        raise HTTPException(status_code=404, detail="Book has no library file")

    root = Path(root_folder.path).resolve()
    epub_path = (root / book.file_path).resolve()
    # file_path must stay inside the root folder
    if not epub_path.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Book file not found")
    if not epub_path.is_file():
        raise HTTPException(status_code=404, detail="Book file not found")

    return FileResponse(
        epub_path,
        media_type="application/epub+zip",
        filename=epub_path.name,
    )


@router.post("/books", status_code=201)
async def create_book(
    body: BookCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if body.status and body.status not in [s.value for s in BookStatus]:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")

    author = _resolve_author(db, body.author_name)

    book = Book(
        title=body.title,
        author_id=author.id if author else None,
        hardcover_id=body.hardcover_id or f"manual-{uuid4().hex}",
        source="manual",
        isbn=body.isbn,
        description=body.description,
        publisher=body.publisher,
        language=body.language,
        tags=body.tags,
        cover_url=body.cover_url,
        series_name=body.series_name,
        series_position=body.series_position,
        status=body.status,
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    if book.status in {BookStatus.WANTED.value, BookStatus.MISSING.value}:
        search_on_add = load_config().get("pipeline", {}).get("search_on_add", True)
        pipeline = getattr(request.app.state, "pipeline", None)
        if search_on_add and pipeline is not None:
            background_tasks.add_task(pipeline.search_single_book, book.id)
        elif search_on_add:
            logger.warning("search_on_add=true but pipeline service is not initialized — skipping auto-search")

    return book.to_dict()


@router.put("/books/{book_id}")
async def update_book(book_id: int, body: BookUpdateRequest, db: Session = Depends(get_db)):
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    update_data = body.model_dump(exclude_unset=True)

    if "author_name" in update_data:
        author = _resolve_author(db, update_data.pop("author_name"))
        book.author_id = author.id if author else None
    else:
        update_data.pop("author_name", None)

    if "status" in update_data and update_data["status"] not in [s.value for s in BookStatus]:
        raise HTTPException(status_code=422, detail=f"Invalid status: {update_data['status']}")

    for field, value in update_data.items():
        setattr(book, field, value)

    book.updated_at = naive_utcnow()

    if book.file_path and book.root_folder_id:
        try:
            root_folder = db.query(RootFolder).filter(RootFolder.id == book.root_folder_id).first()
            if root_folder:
                epub_path = os.path.join(root_folder.path, book.file_path)
                if os.path.exists(epub_path):
                    author_name = book.author.name if book.author else None
                    metadata = EpubMetadata(
                        title=book.title,
                        authors=[author_name] if author_name else [],
                        series=book.series_name,
                        series_position=book.series_position,
                        description=book.description,
                        publisher=book.publisher,
                        language=book.language,
                    )
                    EpubService().write_metadata(epub_path, metadata)
                    book.epub_meta_state = EpubMetaState.SYNCED.value
                    book.epub_meta_synced_at = naive_utcnow()
                    book.epub_meta_attempts = 0
        except Exception as e:
            logger.warning("Failed to write EPUB metadata for book %s: %s", book_id, e)
            # Fresh retry budget: the pipeline self-heal stage re-verifies and
            # rewrites (or settles drm/failed) on its next pass.
            book.epub_meta_state = None
            book.epub_meta_attempts = 0

    db.commit()
    db.refresh(book)

    return book.to_dict()


@router.post("/books/{book_id}/retry", status_code=202)
def force_retry_book(book_id: int, db: Session = Depends(get_db)):
    """Force-retry a FAILED or PERMANENT_FAILED book.

    Resets status to WANTED and clears retry_count, failure_reason, and low_confidence
    so the next pipeline tick will pick it up again.
    """
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    retryable_statuses = {BookStatus.FAILED.value, BookStatus.PERMANENT_FAILED.value}
    if book.status not in retryable_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Book is not in a retryable state, current status: {book.status}",
        )

    previous_status = book.status
    if book.failure_reason:
        _append_failure_history(book, book.failure_reason)
    _append_failure_history(book, "MANUAL_RETRY")
    book.status = BookStatus.WANTED.value
    book.retry_count = 0
    book.failure_reason = None
    book.low_confidence = False
    book.updated_at = naive_utcnow()
    db.commit()

    try:
        from backend.services.websocket_manager import manager as ws_manager

        ws_manager.broadcast_sync(
            "book_force_retried",
            {
                "book_id": book_id,
                "previous_status": previous_status,
                "new_status": BookStatus.WANTED.value,
            },
        )
    except Exception as e:
        logger.debug("WS broadcast failed for force_retry_book(%s): %s", book_id, e)

    return {
        "book_id": book_id,
        "previous_status": previous_status,
        "new_status": BookStatus.WANTED.value,
    }


@router.post("/books/{book_id}/kindle-requeue", status_code=202)
def requeue_kindle_delivery(
    book_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Queue a book for Kindle delivery ("Send to Kindle").

    Allowed from any state except an active transfer: never-queued (NULL),
    SKIPPED (gave up after the delivery window) and DELIVERED (send again,
    e.g. after deleting it from the device) all reset to PENDING. PENDING is
    idempotent (double-clicks are harmless); IN_PROGRESS returns 409.

    After queueing, kicks the Kindle delivery pipeline stage in the background
    so the transfer starts within seconds when the device is online; when it
    is off, the book waits in the queue and the scheduled tick delivers later.
    """
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    if book.kindle_delivery_status == KindleDeliveryStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="Kindle delivery already in progress for this book")
    if not book.file_path or book.root_folder_id is None:
        raise HTTPException(status_code=400, detail="Book has no library file to deliver")

    pipeline = getattr(request.app.state, "pipeline", None)

    # A manual send is a pin: mirror cleanup keeps this book on the device
    # regardless of its Hardcover shelf, until the user unpins it.
    if not book.kindle_pinned:
        book.kindle_pinned = True
        db.commit()

    if book.kindle_delivery_status == KindleDeliveryStatus.PENDING.value:
        return {
            "book_id": book_id,
            "previous_status": KindleDeliveryStatus.PENDING.value,
            "new_status": KindleDeliveryStatus.PENDING.value,
            "already_queued": True,
            "kicked": False,
        }

    previous_status = book.kindle_delivery_status
    book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
    book.kindle_first_pending_at = naive_utcnow()
    book.kindle_delivery_attempts = 0
    book.updated_at = naive_utcnow()
    db.commit()

    try:
        from backend.services.websocket_manager import manager as ws_manager

        ws_manager.broadcast_sync(
            "kindle_delivery_requeued",
            {
                "book_id": book_id,
                "previous_status": previous_status,
                "new_status": KindleDeliveryStatus.PENDING.value,
            },
        )
    except Exception as e:
        logger.debug("WS broadcast failed for kindle-requeue(%s): %s", book_id, e)

    if pipeline is not None:
        background_tasks.add_task(pipeline.kick_kindle_delivery)

    return {
        "book_id": book_id,
        "previous_status": previous_status,
        "new_status": KindleDeliveryStatus.PENDING.value,
        "already_queued": False,
        "kicked": pipeline is not None,
    }


class RenameApplyRequest(BaseModel):
    book_ids: list[int] | None = None


@router.get("/rename/preview")
async def rename_preview(db: Session = Depends(get_db)):
    """Radarr-style preview: old -> new path for every in-library book."""
    items = RenameService(db).preview()
    return {
        "total": len(items),
        "changed_count": sum(1 for item in items if item.changed),
        "items": [item.to_dict() for item in items],
    }


@router.post("/rename")
async def rename_apply(body: RenameApplyRequest, db: Session = Depends(get_db)):
    """Apply the naming template to library files, optionally limited to book_ids."""
    try:
        return RenameService(db).apply(book_ids=body.book_ids)
    except PipelineError as exc:
        if exc.reason == FailureReason.PIPELINE_LOCK_HELD:
            raise HTTPException(status_code=409, detail=str(exc))
        raise


@router.delete("/books/{book_id}/kindle-pin")
def unpin_kindle_delivery(book_id: int, db: Session = Depends(get_db)):
    """Clear a book's Kindle pin; the next mirror sync removes it from the device."""
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    was_pinned = book.kindle_pinned
    if was_pinned:
        book.kindle_pinned = False
        book.updated_at = naive_utcnow()
        db.commit()

    return {"book_id": book_id, "was_pinned": was_pinned, "kindle_pinned": False}


@router.delete("/books/{book_id}")
async def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    if book.file_path and book.root_folder_id:
        try:
            root_folder = db.query(RootFolder).filter(RootFolder.id == book.root_folder_id).first()
            if root_folder:
                epub_path = os.path.join(root_folder.path, book.file_path)
                if os.path.exists(epub_path):
                    os.remove(epub_path)
                    logger.info("Removed EPUB file: %s", epub_path)
        except Exception as e:
            logger.warning("Failed to remove EPUB file for book %s: %s", book_id, e)

    db.delete(book)
    db.commit()

    return {"success": True, "message": f"Book {book_id} deleted"}
