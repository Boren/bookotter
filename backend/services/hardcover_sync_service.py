# pyright: reportCallIssue=false, reportArgumentType=false, reportOptionalCall=false, reportAttributeAccessIssue=false

"""
Hardcover sync service: polls Hardcover lists and adds new books to the library DB.
Also handles E-reader sync from library DB (books with IN_LIBRARY status).
"""

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.clients.ereader_client import EreaderClient
from backend.clients.hardcover_client import HardcoverClient
from backend.config import get_ereader_by_id, get_ereader_sync_shelves
from backend.models.book import Author, Book, BookStatus, EreaderDeliveryStatus
from backend.utils.clock import naive_utcnow
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
    """Syncs books from Hardcover lists into the local library DB and transfers to E-reader."""

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
        """Poll Hardcover shelves, add new books, and mirror shelf membership onto Book.hardcover_status."""
        # `sync.include_statuses` gates which shelves may CREATE new library books.
        # All shelves are always fetched so hardcover_status stays an accurate
        # mirror: a book moving between shelves (or off every shelf) must be
        # tracked even when its destination shelf isn't imported.
        sync_config = self.config.get("sync", {}).get("include_statuses", {})
        include_shelves = {
            name
            for name in HARDCOVER_STATUS_MAP
            if sync_config.get(
                name, name == "want_to_read"
            )  # want_to_read defaults True, matching get_default_config()
        }
        status_id_to_name = {v: k for k, v in HARDCOVER_STATUS_MAP.items()}

        logger.info(f"Syncing Hardcover shelves (importing new books from: {sorted(include_shelves) or 'none'})")

        try:
            hc_books = self.hardcover_client.get_books_by_status(list(HARDCOVER_STATUS_MAP.values()))
        except Exception as e:
            logger.error(f"Failed to fetch books from Hardcover: {e}")
            return {"new_books": 0, "new_book_ids": [], "existing_skipped": 0, "errors": 1}

        new_book_ids: list[int] = []
        new_books = 0
        existing_skipped = 0
        errors = 0
        seen_book_ids: set[int] = set()

        for hc_book in hc_books:
            try:
                hardcover_id = str(hc_book.get("hardcover_id", "")) or None
                isbns = hc_book.get("isbns", [])
                isbn = isbns[0] if isbns else None

                if not hardcover_id and not isbn:
                    logger.warning(f"Skipping book with no identifier (title={hc_book.get('title')!r})")
                    errors += 1
                    continue

                status_id = hc_book.get("status_id")
                shelf = status_id_to_name.get(status_id) if status_id is not None else None

                existing = None
                if hardcover_id:
                    existing = db.query(Book).filter(Book.hardcover_id == hardcover_id).first()
                if existing is None and isbn:
                    existing = db.query(Book).filter(Book.isbn == isbn).first()
                if existing:
                    if existing.hardcover_status != shelf:
                        existing.hardcover_status = shelf
                    seen_book_ids.add(existing.id)
                    existing_skipped += 1
                    continue

                if shelf not in include_shelves:
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
                    hardcover_status=shelf,
                )
                db.add(book)
                db.commit()

                new_books += 1
                new_book_ids.append(book.id)
                seen_book_ids.add(book.id)
                logger.info(f"Added new book from Hardcover: '{book.title}' (hc_id={hardcover_id})")

            except Exception as e:
                logger.error(f"Error processing Hardcover book '{hc_book.get('title', '?')}': {e}")
                db.rollback()
                errors += 1

        # Absence pass: a book that previously had a shelf but appeared on none
        # this run has left every Hardcover shelf — clear its mirror status.
        # Guarded so a pathological empty API response can never blank the whole
        # mirror set (which would make the next E-reader sync wipe the device).
        if hc_books:
            cleared = (
                db.query(Book)
                .filter(Book.hardcover_status.isnot(None), Book.id.notin_(seen_book_ids))
                .update({Book.hardcover_status: None}, synchronize_session=False)
            )
            if cleared:
                logger.info(f"Cleared shelf status for {cleared} book(s) no longer on any Hardcover shelf")
        else:
            logger.warning("Hardcover returned 0 books across all shelves — skipping shelf-absence pass")
        db.commit()

        logger.info(f"Hardcover sync complete: {new_books} new, {existing_skipped} skipped, {errors} errors")
        return {
            "new_books": new_books,
            "new_book_ids": new_book_ids,
            "existing_skipped": existing_skipped,
            "errors": errors,
        }

    def run_ereader_sync(self, ereader_device_id: str, db: Session, dry_run: bool = False) -> dict:
        """Mirror the ereader-sync shelves (plus pinned books) onto a E-reader device.

        Sends shelf/pinned IN_LIBRARY books missing from the device, then (when
        cleanup is enabled) deletes every other book file from the device. With
        dry_run=True nothing is transferred, deleted, or written to the DB; the
        returned dict carries would_send / would_delete previews instead.
        """
        ereader_config = get_ereader_by_id(ereader_device_id)
        if not ereader_config:
            logger.error(f"E-reader device not found: {ereader_device_id}")
            return {
                "error": f"E-reader device '{ereader_device_id}' not found",
                "transferred": 0,
                "skipped": 0,
                "failed": 0,
            }

        ereader_client = EreaderClient.from_config(ereader_config)

        sync_shelves = get_ereader_sync_shelves(self.config)
        books = (
            db.query(Book)
            .filter(
                Book.status == BookStatus.IN_LIBRARY,
                Book.file_path.isnot(None),
                or_(Book.hardcover_status.in_(sync_shelves), Book.ereader_pinned.is_(True)),
            )
            .all()
        )

        logger.info(
            f"E-reader sync: {len(books)} book(s) in mirror set "
            f"(shelves={sorted(sync_shelves) or 'none'} + pinned){' [dry run]' if dry_run else ''}"
        )

        if self.emit_callback and not dry_run:
            self.emit_callback(
                "ereader_sync_started",
                {"ereader_id": ereader_device_id, "total_books": len(books)},
            )

        transfer_cfg = self.config.get("transfer", {})
        folder_org = transfer_cfg.get("folder_organization", "flat")
        protected_paths = transfer_cfg.get("cleanup_protected_paths", [])

        # The mirror set as remote paths: every selected book, whether or not it
        # still transfers this run — cleanup must never delete a mirror-set book.
        expected_remote_paths = [
            ereader_client.generate_remote_path(
                os.path.basename(book.file_path or ""),
                author=book.author.name if book.author else "",
                series=book.series_name or "",
                folder_organization=folder_org,
            )
            for book in books
        ]

        # Cleanup safety valve: until the first Hardcover sync has backfilled
        # hardcover_status, the mirror set is empty-looking and cleanup would
        # wipe the device. Skip cleanup entirely in that state.
        statuses_backfilled = db.query(Book.id).filter(Book.hardcover_status.isnot(None)).first() is not None
        cleanup_wanted = transfer_cfg.get("cleanup_enabled", True)
        if cleanup_wanted and not statuses_backfilled:
            logger.warning(
                "E-reader cleanup skipped: no book has a Hardcover shelf status yet (run a Hardcover sync first)"
            )

        if dry_run:
            device_basenames = {os.path.basename(p) for p in ereader_client.list_all_books()}
            would_send = [
                {"book_id": book.id, "title": book.title, "remote_path": remote_path}
                for book, remote_path in zip(books, expected_remote_paths, strict=True)
                if os.path.basename(remote_path) not in device_basenames
            ]
            would_delete = []
            if cleanup_wanted and statuses_backfilled:
                would_delete = ereader_client.find_orphaned_books(expected_remote_paths, protected_paths)
            logger.info(f"E-reader sync dry run: would send {len(would_send)}, would delete {len(would_delete)}")
            return {
                "transferred": 0,
                "skipped": 0,
                "failed": 0,
                "cleanup": None,
                "dry_run": True,
                "would_send": would_send,
                "would_delete": would_delete,
            }

        transferred = 0
        skipped = 0
        failed = 0

        for book in books:
            try:
                if not book.root_folder or not book.file_path:
                    logger.warning(f"Book '{book.title}' has no root_folder or file_path, skipping E-reader transfer")
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
                result = ereader_client.transfer_file(
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
                        book.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
                    else:
                        transferred += 1
                        book.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
                        logger.info(f"Transferred '{book.title}' to E-reader ({result.get('file_size', 0)} bytes)")
                        log_event(
                            "ereader_delivered",
                            book_id=book.id,
                            ereader_id=ereader_device_id,
                            duration_ms=transfer_duration_ms,
                            size_bytes=result.get("file_size", 0),
                        )
                    book.ereader_delivered_at = naive_utcnow()
                    if self.emit_callback:
                        self.emit_callback(
                            "ereader_delivered",
                            {"book_id": book.id, "status": result["status"]},
                        )
                else:
                    failed += 1
                    logger.error(f"Failed to transfer '{book.title}': {result.get('error')}")

            except Exception as e:
                logger.error(f"Error transferring '{book.title}' to E-reader: {e}")
                failed += 1

        db.commit()

        cleanup_result = None
        if cleanup_wanted and statuses_backfilled:
            cleanup_result = ereader_client.cleanup_orphaned_books(
                expected_remote_paths,
                protected_paths,
                delete_sdr=transfer_cfg.get("cleanup_sdr_folders", True),
            )
            log_event("ereader_cleanup", ereader_id=ereader_device_id, **cleanup_result)

        # Reconcile delivery state: books that left the mirror set were (or will
        # be) removed from the device — clear their delivery tracking so the UI
        # and the delivery pipeline don't treat them as on-device or pending.
        mirror_ids = [book.id for book in books]
        reconciled = (
            db.query(Book)
            .filter(Book.ereader_delivery_status.isnot(None), Book.id.notin_(mirror_ids))
            .update(
                {
                    Book.ereader_delivery_status: None,
                    Book.ereader_delivered_at: None,
                    Book.ereader_first_pending_at: None,
                    Book.ereader_delivery_attempts: 0,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if reconciled:
            logger.info(f"Reset E-reader delivery state for {reconciled} book(s) no longer in the mirror set")

        logger.info(f"E-reader sync complete: {transferred} transferred, {skipped} skipped, {failed} failed")
        if self.emit_callback:
            self.emit_callback(
                "ereader_sync_completed",
                {"transferred": transferred, "skipped": skipped, "failed": failed},
            )
        return {
            "transferred": transferred,
            "skipped": skipped,
            "failed": failed,
            "cleanup": cleanup_result,
            "dry_run": False,
        }
