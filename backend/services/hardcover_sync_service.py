# pyright: reportCallIssue=false, reportArgumentType=false, reportOptionalCall=false, reportAttributeAccessIssue=false

"""
Hardcover sync service: polls Hardcover lists and adds new books to the library DB.
Also handles Kindle sync from library DB (books with IN_LIBRARY status).
"""

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.clients.hardcover_client import HardcoverClient
from backend.clients.kindle_client import KindleClient
from backend.config import get_kindle_by_id
from backend.models.book import Author, Book, BookStatus, KindleDeliveryStatus
from backend.utils.events import log_event
from backend.utils.transfer_progress import make_progress_callback

logger = logging.getLogger(__name__)

# Hardcover status name → API status ID (1=want_to_read, 2=currently_reading, 3=read)
HARDCOVER_STATUS_MAP = {
    "want_to_read": 1,
    "currently_reading": 2,
    "read": 3,
}


def _get_or_create_author(db: Session, name: str) -> Author:
    """Race-safe author get-or-create.

    SELECTs first; if missing, INSERTs and catches IntegrityError raised by
    Author.name UNIQUE constraint when a concurrent transaction inserted the
    same name. On conflict, rolls back and re-SELECTs the winning row.
    """
    existing = db.query(Author).filter(Author.name == name).first()
    if existing:
        return existing
    try:
        author = Author(name=name)
        db.add(author)
        db.flush()
        return author
    except IntegrityError:
        db.rollback()
        return db.query(Author).filter(Author.name == name).one()


class HardcoverSyncService:
    """Syncs books from Hardcover lists into the local library DB and transfers to Kindle."""

    def __init__(
        self,
        hardcover_client: HardcoverClient,
        config: dict,
        emit_callback: Callable[..., Any] | None = None,
    ):
        self.hardcover_client = hardcover_client
        self.config = config
        self.emit_callback = emit_callback

    def sync_hardcover_lists(self, db: Session) -> dict:
        """Poll Hardcover for books with enabled statuses and add new ones to the DB."""
        # `sync.include_statuses` is the UI-controlled toggle for which statuses to fetch.
        # `pipeline.status_actions` controls per-status downstream actions (download /
        # kindle_sync), not whether a status is fetched from Hardcover in the first place.
        sync_config = self.config.get("sync", {}).get("include_statuses", {})

        status_ids: list[int] = []
        if sync_config.get("currently_reading", False):
            status_ids.append(HARDCOVER_STATUS_MAP["currently_reading"])
        if sync_config.get("want_to_read", True):  # default True matches get_default_config()
            status_ids.append(HARDCOVER_STATUS_MAP["want_to_read"])
        if sync_config.get("read", False):
            status_ids.append(HARDCOVER_STATUS_MAP["read"])

        if not status_ids:
            logger.info("No Hardcover statuses enabled in sync.include_statuses, skipping sync")
            return {"new_books": 0, "new_book_ids": [], "existing_skipped": 0, "errors": 0}

        logger.info(f"Syncing Hardcover lists for status IDs: {status_ids}")

        try:
            hc_books = self.hardcover_client.get_books_by_status(status_ids)
        except Exception as e:
            logger.error(f"Failed to fetch books from Hardcover: {e}")
            return {"new_books": 0, "new_book_ids": [], "existing_skipped": 0, "errors": 1}

        new_book_ids: list[int] = []
        new_books = 0
        existing_skipped = 0
        errors = 0

        for hc_book in hc_books:
            try:
                hardcover_id = str(hc_book.get("hardcover_id", "")) or None
                isbns = hc_book.get("isbns", [])
                isbn = isbns[0] if isbns else None

                if not hardcover_id and not isbn:
                    logger.warning(f"Skipping book with no identifier (title={hc_book.get('title')!r})")
                    errors += 1
                    continue

                if hardcover_id:
                    existing = db.query(Book).filter(Book.hardcover_id == hardcover_id).first()
                    if existing:
                        existing_skipped += 1
                        continue

                if isbn:
                    existing = db.query(Book).filter(Book.isbn == isbn).first()
                    if existing:
                        existing_skipped += 1
                        continue

                author_name = ""
                authors_list = hc_book.get("authors", [])
                if authors_list:
                    author_name = authors_list[0]
                elif hc_book.get("author_string"):
                    author_name = hc_book["author_string"]

                author = _get_or_create_author(db, author_name) if author_name else None

                book = Book(
                    title=hc_book.get("title", ""),
                    hardcover_id=hardcover_id,
                    isbn=isbn,
                    cover_url=hc_book.get("cover_url"),
                    series_name=hc_book.get("series_name"),
                    series_position=hc_book.get("series_position"),
                    status=BookStatus.MISSING,
                    author_id=author.id if author else None,
                    description=hc_book.get("description"),
                    publisher=None,
                    language=None,
                )
                db.add(book)
                db.commit()

                new_books += 1
                new_book_ids.append(book.id)
                logger.info(f"Added new book from Hardcover: '{book.title}' (hc_id={hardcover_id})")

            except Exception as e:
                logger.error(f"Error processing Hardcover book '{hc_book.get('title', '?')}': {e}")
                db.rollback()
                errors += 1

        logger.info(f"Hardcover sync complete: {new_books} new, {existing_skipped} skipped, {errors} errors")
        return {
            "new_books": new_books,
            "new_book_ids": new_book_ids,
            "existing_skipped": existing_skipped,
            "errors": errors,
        }

    def run_kindle_sync(self, kindle_device_id: str, db: Session) -> dict:
        """Transfer IN_LIBRARY books with files to a Kindle device."""
        kindle_config = get_kindle_by_id(kindle_device_id)
        if not kindle_config:
            logger.error(f"Kindle device not found: {kindle_device_id}")
            return {
                "error": f"Kindle device '{kindle_device_id}' not found",
                "transferred": 0,
                "skipped": 0,
                "failed": 0,
            }

        kindle_client = KindleClient.from_config(kindle_config)

        books = db.query(Book).filter(Book.status == BookStatus.IN_LIBRARY, Book.file_path.isnot(None)).all()

        logger.info(f"Kindle sync: found {len(books)} IN_LIBRARY book(s) with files")

        if self.emit_callback:
            self.emit_callback(
                "kindle_sync_started",
                {"kindle_id": kindle_device_id, "total_books": len(books)},
            )

        folder_org = self.config.get("transfer", {}).get("folder_organization", "flat")

        transferred = 0
        skipped = 0
        failed = 0

        for book in books:
            try:
                if not book.root_folder or not book.file_path:
                    logger.warning(f"Book '{book.title}' has no root_folder or file_path, skipping Kindle transfer")
                    skipped += 1
                    continue

                # Absolute path = root_folder.path + relative file_path (set during import)
                abs_path = os.path.join(book.root_folder.path, book.file_path)

                if not os.path.exists(abs_path):
                    logger.warning(f"File not found for '{book.title}': {abs_path}")
                    skipped += 1
                    continue

                author_name = book.author.name if book.author else ""
                series = book.series_name or ""

                progress_cb = None
                if self.emit_callback:
                    progress_cb = make_progress_callback(
                        self.emit_callback,
                        "transfer_progress",
                        {"book_id": book.id, "book_title": book.title},
                    )

                transfer_start = time.monotonic()
                result = kindle_client.transfer_file(
                    local_path=abs_path,
                    skip_existing=True,
                    author=author_name,
                    series=series,
                    folder_organization=folder_org,
                    progress_callback=progress_cb,
                )
                transfer_duration_ms = int((time.monotonic() - transfer_start) * 1000)

                if result["success"]:
                    if result["status"] == "skipped":
                        skipped += 1
                        # File is already on the device — record that fact
                        book.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
                    else:
                        transferred += 1
                        book.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
                        logger.info(f"Transferred '{book.title}' to Kindle ({result.get('file_size', 0)} bytes)")
                        log_event(
                            "kindle_delivered",
                            book_id=book.id,
                            kindle_id=kindle_device_id,
                            duration_ms=transfer_duration_ms,
                            size_bytes=result.get("file_size", 0),
                        )
                    book.kindle_delivered_at = datetime.utcnow()
                    if self.emit_callback:
                        self.emit_callback(
                            "kindle_delivered",
                            {"book_id": book.id, "status": result["status"]},
                        )
                else:
                    failed += 1
                    logger.error(f"Failed to transfer '{book.title}': {result.get('error')}")

            except Exception as e:
                logger.error(f"Error transferring '{book.title}' to Kindle: {e}")
                failed += 1

        db.commit()

        logger.info(f"Kindle sync complete: {transferred} transferred, {skipped} skipped, {failed} failed")
        if self.emit_callback:
            self.emit_callback(
                "kindle_sync_completed",
                {"transferred": transferred, "skipped": skipped, "failed": failed},
            )
        return {"transferred": transferred, "skipped": skipped, "failed": failed}
