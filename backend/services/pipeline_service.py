# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""
Pipeline orchestrator: WANTED → SEARCHING → GRABBED → DOWNLOADING → IMPORTING → IN_LIBRARY.

The recurring scheduler (start_monitoring) only advances post-grab stages.
See run_pipeline() for the rationale.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import IntegrityError

from backend.constants import RECONCILE_INTERVAL_MIN
from backend.database import SessionLocal
from backend.errors import FailureReason, PipelineError
from backend.models.book import Book, BookStatus, Download, DownloadStatus, KindleDeliveryStatus, RootFolder
from backend.services.pipeline_states import transition_book, transition_download
from backend.services.torrent_hash import extract_info_hash_from_url
from backend.services.websocket_manager import WebSocketManager
from backend.utils.cleanup import cleanup_orphan_tmp_files
from backend.utils.events import log_event
from backend.utils.pipeline_lock import acquire_pipeline_lock

logger = logging.getLogger(__name__)

PIPELINE_INTERVAL_SECONDS = 15


class PipelineService:
    """
    Orchestrates all book pipeline stages with optional service injection.

    Expected service interfaces:
        search_service.search_book(title: str, author: str) -> list[dict]
        download_service.add_torrent(download: Download) -> bool
        download_service.get_completed_file_path(download: Download) -> str | None
        import_service.import_epub(book: Book, file_path: str) -> bool
    """

    def __init__(
        self,
        search_service: Any | None = None,
        download_service: Any | None = None,
        import_service: Any | None = None,
        db_session_factory: Callable | None = None,
        ws_manager: WebSocketManager | None = None,
        kindle_client: Any | None = None,
    ):
        self.search_service = search_service
        self.download_service = download_service
        self.import_service = import_service
        self._session_factory = db_session_factory or SessionLocal
        self._scheduler: AsyncIOScheduler | None = None
        self.ws_manager = ws_manager
        self.kindle_client = kindle_client
        # Optional active session — tests may inject directly via `service.db = session`.
        # When unset, methods that need it should fall back to self._session_factory().
        self.db: Any | None = None

    def process_wanted_books(self) -> int:
        if self.search_service is None:
            logger.warning("process_wanted_books: no search_service configured, skipping")
            return 0

        db = self._session_factory()
        grabbed = 0
        try:
            books = db.query(Book).filter(Book.status.in_([BookStatus.WANTED, BookStatus.MISSING])).all()
            logger.debug(f"process_wanted_books: {len(books)} WANTED/MISSING book(s) found")
            for book in books:
                try:
                    grabbed += self._search_and_grab(book, db)
                except Exception as exc:
                    logger.error(f"Unexpected error processing wanted/missing book '{book.title}': {exc}")
                    self._fail_book(book, db, str(exc))
            return grabbed
        finally:
            db.close()

    def process_searching_books(self) -> int:
        if self.search_service is None:
            logger.warning("process_searching_books: no search_service configured, skipping")
            return 0

        db = self._session_factory()
        grabbed = 0
        try:
            books = db.query(Book).filter(Book.status == BookStatus.SEARCHING).all()
            logger.debug(f"process_searching_books: {len(books)} SEARCHING book(s) found")
            for book in books:
                try:
                    grabbed += self._search_and_grab(book, db)
                except Exception as exc:
                    logger.error(f"Unexpected error processing SEARCHING book '{book.title}': {exc}")
                    self._fail_book(book, db, str(exc))
            return grabbed
        finally:
            db.close()

    def process_grabbed_books(self) -> int:
        if self.download_service is None:
            logger.warning("process_grabbed_books: no download_service configured, skipping")
            return 0

        db = self._session_factory()
        started = 0
        try:
            books = db.query(Book).filter(Book.status == BookStatus.GRABBED).all()
            logger.debug(f"process_grabbed_books: {len(books)} GRABBED book(s) found")
            for book in books:
                queued = [d for d in book.downloads if d.status == DownloadStatus.QUEUED]
                if not queued:
                    logger.warning(f"Book '{book.title}' is GRABBED but has no QUEUED downloads — failing")
                    self._fail_book(book, db, "No queued downloads for grabbed book")
                    continue
                download = queued[0]
                try:
                    success = self.download_service.add_torrent(download)
                    if success:
                        if transition_download(download, DownloadStatus.DOWNLOADING):
                            db.commit()
                        if self._transition_book(book, BookStatus.DOWNLOADING, download=download):
                            db.commit()
                        started += 1
                        logger.info(f"Download started for '{book.title}'")
                    else:
                        logger.warning(f"add_torrent returned False for '{book.title}'")
                        self._fail_download(download, db, "add_torrent returned False")
                        self._fail_book(book, db, "add_torrent returned False")
                except Exception as exc:
                    logger.error(f"Error adding torrent for '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db, str(exc))
            return started
        finally:
            db.close()

    def process_downloading_books(self) -> int:
        if self.download_service is None:
            logger.warning("process_downloading_books: no download_service configured, skipping")
            return 0

        db = self._session_factory()
        importing = 0
        try:
            books = db.query(Book).filter(Book.status == BookStatus.DOWNLOADING).all()
            logger.debug(f"process_downloading_books: {len(books)} DOWNLOADING book(s) found")
            for book in books:
                active = [d for d in book.downloads if d.status == DownloadStatus.DOWNLOADING]
                if not active:
                    logger.warning(f"Book '{book.title}' is DOWNLOADING but has no active downloads — failing")
                    self._fail_book(book, db, "No active downloads for downloading book")
                    continue
                download = active[0]
                try:
                    file_path = self.download_service.get_completed_file_path(download)
                    if file_path is None:
                        continue
                    download.file_path = str(file_path)
                    download.completed_at = datetime.now(UTC)
                    if transition_download(download, DownloadStatus.COMPLETED):
                        db.commit()
                    if self._transition_book(book, BookStatus.IMPORTING, download=download):
                        db.commit()
                    importing += 1
                    logger.info(f"Download complete for '{book.title}': {file_path}")
                except Exception as exc:
                    logger.error(f"Error checking download for '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db, str(exc))
            return importing
        finally:
            db.close()

    def process_importing_books(self) -> int:
        if self.import_service is None:
            logger.warning("process_importing_books: no import_service configured, skipping")
            return 0

        db = self._session_factory()
        imported = 0
        try:
            books = db.query(Book).filter(Book.status == BookStatus.IMPORTING).all()
            logger.debug(f"process_importing_books: {len(books)} IMPORTING book(s) found")
            for book in books:
                completed = [d for d in book.downloads if d.status == DownloadStatus.COMPLETED]
                if not completed:
                    logger.warning(f"Book '{book.title}' is IMPORTING but has no COMPLETED downloads — failing")
                    self._fail_book(book, db, "No completed downloads for importing book")
                    continue
                download = completed[0]
                if not download.file_path:
                    logger.warning(f"Download for '{book.title}' has no file_path — failing")
                    self._fail_download(download, db, "No file path recorded after download")
                    self._fail_book(book, db, "No file path recorded after download")
                    continue
                try:
                    success = self.import_service.import_epub(book, download.file_path)
                    if success:
                        if transition_download(download, DownloadStatus.IMPORTING):
                            db.commit()
                        if transition_download(download, DownloadStatus.IMPORTED):
                            db.commit()
                        if self._transition_book(book, BookStatus.IN_LIBRARY, download=download):
                            db.commit()
                        imported += 1
                        logger.info(f"Imported '{book.title}' to library")
                    else:
                        logger.warning(f"import_epub returned False for '{book.title}'")
                        self._fail_download(download, db, "import_epub returned False")
                        self._fail_book(book, db, "import_epub returned False")
                except Exception as exc:
                    logger.error(f"Error importing '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db, str(exc))
            return imported
        finally:
            db.close()

    def process_failed_books(self) -> int:
        """Auto-retry FAILED books with exponential cool-down and retry budget."""
        from backend.constants import PIPELINE_AUTO_RETRY_ATTEMPTS, RETRY_BASE_DELAY

        db = self._session_factory()
        retried = 0
        changed = False
        now = datetime.utcnow()

        try:
            failed_books = db.query(Book).filter(Book.status == BookStatus.FAILED.value).all()
            logger.debug("process_failed_books: %d FAILED book(s) found", len(failed_books))

            for book in failed_books:
                retry_count = book.retry_count if isinstance(book.retry_count, int) else 0

                if retry_count >= PIPELINE_AUTO_RETRY_ATTEMPTS:
                    book.status = BookStatus.PERMANENT_FAILED.value
                    book.failure_reason = FailureReason.RETRY_BUDGET_EXHAUSTED.value
                    changed = True
                    logger.info("Book %s exhausted retry budget → PERMANENT_FAILED", book.id)
                    log_event(
                        "book_permanent_failed",
                        book_id=book.id,
                        reason=book.failure_reason,
                    )
                    continue

                cooldown = timedelta(seconds=RETRY_BASE_DELAY * (2**retry_count))
                if book.updated_at and (now - book.updated_at) < cooldown:
                    continue

                book.retry_count = retry_count + 1
                book.status = BookStatus.WANTED.value
                book.failure_reason = None
                retried += 1
                changed = True
                logger.info(
                    "Auto-retrying book %s (attempt %d/%d)",
                    book.id,
                    book.retry_count,
                    PIPELINE_AUTO_RETRY_ATTEMPTS,
                )
                log_event(
                    "book_retried",
                    book_id=book.id,
                    retry_count=book.retry_count,
                    max_attempts=PIPELINE_AUTO_RETRY_ATTEMPTS,
                )

            if changed:
                db.commit()

            return retried
        finally:
            db.close()

    def _get_kindle_config(self) -> dict | None:
        """Return the active Kindle config dict, or None when not configured.

        Default stub returns None — overridden by tests, CLI, or future DI to
        supply the dict consumed by KindleClient.from_config().
        """
        return None

    def process_kindle_delivery_books(self) -> int:
        """Drive the Kindle delivery state machine.

        PENDING:
            - Stamp kindle_first_pending_at if missing.
            - If now - first_pending_at > KINDLE_DELIVERY_TIMEOUT_DAYS → SKIPPED.
            - Otherwise attempt SFTP transfer:
                success → DELIVERED
                failure → stays PENDING (retry next cycle)
              kindle_delivery_attempts increments on every transfer attempt.

        SKIPPED:
            - Ping Kindle (_get_or_create_ssh). If reachable → re-arm as
              PENDING with a fresh kindle_first_pending_at (auto-recover).

        Returns:
            Number of PENDING books that reached a terminal state
            (DELIVERED or SKIPPED) during this run.
        """
        from backend.constants import KINDLE_DELIVERY_TIMEOUT_DAYS

        if self.db is None or self.kindle_client is None:
            logger.warning(
                "process_kindle_delivery_books: db or kindle_client not configured, skipping"
            )
            return 0

        now = datetime.utcnow()
        timeout = timedelta(days=KINDLE_DELIVERY_TIMEOUT_DAYS)

        # Snapshot SKIPPED *before* mutating PENDING so a freshly-timed-out
        # book is not immediately re-armed by the auto-retry loop in the
        # same call (would create a PENDING↔SKIPPED bounce).
        skipped_books = (
            self.db.query(Book)
            .filter(Book.kindle_delivery_status == KindleDeliveryStatus.SKIPPED.value)
            .all()
        )
        pending_books = (
            self.db.query(Book)
            .filter(Book.kindle_delivery_status == KindleDeliveryStatus.PENDING.value)
            .all()
        )

        processed = 0
        for book in pending_books:
            if book.kindle_first_pending_at is None:
                book.kindle_first_pending_at = now

            if (now - book.kindle_first_pending_at) > timeout:
                book.kindle_delivery_status = KindleDeliveryStatus.SKIPPED.value
                logger.info("Kindle delivery timed out for book %s — marking SKIPPED", book.id)
                processed += 1
                continue

            kindle_config = self._get_kindle_config()
            if kindle_config is None:
                continue

            try:
                book.kindle_delivery_status = KindleDeliveryStatus.IN_PROGRESS.value
                self.kindle_client.transfer_file(book.file_path)
                book.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
                book.kindle_delivery_attempts = (book.kindle_delivery_attempts or 0) + 1
                processed += 1
            except Exception as exc:
                book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
                book.kindle_delivery_attempts = (book.kindle_delivery_attempts or 0) + 1
                logger.warning("Kindle delivery failed for book %s: %s", book.id, exc)

        for book in skipped_books:
            kindle_config = self._get_kindle_config()
            if kindle_config is None:
                continue
            try:
                self.kindle_client._get_or_create_ssh(kindle_config)
            except Exception:
                continue
            book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
            book.kindle_first_pending_at = now

        self.db.commit()
        return processed

    def run_pipeline(self, holder: str = "scheduled") -> dict[str, Any]:
        """
        Run failed-book recovery and post-grab pipeline stages under an advisory DB lock.

        Pre-grab search stages are intentionally absent — searches are user-initiated
        (search.py routes, /api/wanted/search-all) or future RSS sync, never on a timer.

        Args:
            holder: Identifier of caller — "scheduled" (APScheduler), "manual" (API), "cli".

        Returns:
            Per-stage result counts when the lock is acquired, e.g. {"grabbed": 1, ...}.
            When another run already holds the lock, returns {"skipped": True, "reason": "lock_held"}
            instead of raising — this is the canonical signal for callers to surface a 409 / skip log.
        """
        logger.debug("Pipeline run starting (post-grab stages only, holder=%s)", holder)
        db = self._session_factory()
        try:
            try:
                with acquire_pipeline_lock(db, holder=holder) as run_id:
                    logger.info("Pipeline run started: run_id=%s holder=%s", run_id, holder)
                    log_event("pipeline_run_started", run_id=run_id, holder=holder)
                    run_start = time.monotonic()
                    results: dict[str, Any] = {"failed_retried": self.process_failed_books()}
                    for stage_name, method in [
                        ("grabbed", self.process_grabbed_books),
                        ("downloading", self.process_downloading_books),
                        ("importing", self.process_importing_books),
                    ]:
                        try:
                            results[stage_name] = method()
                        except Exception as exc:
                            logger.error(f"Pipeline stage '{stage_name}' raised: {exc}")
                            results[stage_name] = 0
                    duration_ms = int((time.monotonic() - run_start) * 1000)
                    log_event(
                        "pipeline_run_completed",
                        run_id=run_id,
                        holder=holder,
                        duration_ms=duration_ms,
                        failed_retried=results.get("failed_retried", 0),
                        grabbed=results.get("grabbed", 0),
                        downloading=results.get("downloading", 0),
                        importing=results.get("importing", 0),
                    )
                    logger.debug(f"Pipeline run complete: {results}")
                    return results
            except PipelineError as exc:
                if exc.reason == FailureReason.PIPELINE_LOCK_HELD:
                    logger.info("Pipeline lock held, skipping run (holder=%s): %s", holder, exc)
                    return {"skipped": True, "reason": "lock_held"}
                raise
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(f"Error closing pipeline lock session: {exc}")

    def _get_root_dirs(self) -> list:
        """Get list of root folder paths from database."""
        from pathlib import Path

        db = self._session_factory()
        try:
            folders = db.query(RootFolder).all()
            return [Path(str(f.path)) for f in folders]
        finally:
            db.close()

    def start_monitoring(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            logger.debug("Pipeline scheduler already running")
            return

        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone=UTC,
            job_defaults={"coalesce": True, "max_instances": 1},
        )
        self._scheduler.add_job(
            self.run_pipeline,
            trigger=IntervalTrigger(seconds=PIPELINE_INTERVAL_SECONDS),
            id="pipeline_all_stages",
            name="Pipeline: all stages",
            replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: cleanup_orphan_tmp_files(self._get_root_dirs()),
            trigger=IntervalTrigger(hours=1),
            id="cleanup_tmp_files",
            name="Cleanup: orphan tmp files",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._run_reconcile_state,
            trigger=IntervalTrigger(minutes=RECONCILE_INTERVAL_MIN),
            id="reconcile_state",
            name="Reconciliation: orphan books",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(f"Pipeline monitoring started (interval={PIPELINE_INTERVAL_SECONDS}s)")

    def stop_monitoring(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Pipeline monitoring stopped")

    def _run_reconcile_state(self) -> dict[str, int]:
        empty: dict[str, int] = {"importing_orphans": 0, "downloading_orphans": 0}
        if self.download_service is None:
            logger.debug("_run_reconcile_state: no download_service configured, skipping")
            return empty

        from backend.services.download_service import reconcile_state

        db = self._session_factory()
        try:
            return reconcile_state(db, self.download_service.qbit)
        except Exception as exc:
            logger.error(f"Periodic reconciliation error: {exc}")
            return empty
        finally:
            db.close()

    def _search_and_grab(self, book: Book, db: Any) -> int:
        author_name = book.author.name if book.author else ""

        if book.status in {BookStatus.WANTED, BookStatus.MISSING}:
            if not self._transition_book(book, BookStatus.SEARCHING):
                logger.warning(f"Could not transition '{book.title}' to SEARCHING from {book.status}, skipping")
                return 0

        book.search_attempts = (book.search_attempts or 0) + 1
        book.last_searched_at = datetime.now(UTC)
        db.commit()

        search_start = time.monotonic()
        results = self.search_service.search_book(book.title, author_name)
        search_duration_ms = int((time.monotonic() - search_start) * 1000)
        log_event(
            "book_searched",
            book_id=book.id,
            duration_ms=search_duration_ms,
            results=len(results) if results else 0,
            attempt=book.search_attempts,
        )
        if not results:
            logger.info(
                f"No EPUB results for '{book.title}' — returning to WANTED for retry (attempt {book.search_attempts})"
            )
            # Return book to WANTED state for retry on next pipeline cycle
            if not self._transition_book(book, BookStatus.WANTED):
                logger.warning(f"Could not transition '{book.title}' back to WANTED, leaving in current state")
            db.commit()
            return 0

        approved_results = [result for result in results if getattr(result, "approved", True)]
        if not approved_results:
            logger.info(
                f"No approved results for '{book.title}' — returning to WANTED for retry (attempt {book.search_attempts})"
            )
            if not self._transition_book(book, BookStatus.WANTED):
                logger.warning(f"Could not transition '{book.title}' back to WANTED, leaving in current state")
            db.commit()
            return 0

        best = approved_results[0]
        best_title = best.get("title") if isinstance(best, dict) else best.title
        best_indexer = best.get("indexer") if isinstance(best, dict) else best.indexer
        best_download_url = best.get("download_url") if isinstance(best, dict) else best.download_url
        best_magnet_url = best.get("magnet_url") if isinstance(best, dict) else best.magnet_url
        best_size = best.get("size") if isinstance(best, dict) else best.size
        best_seeders = best.get("seeders") if isinstance(best, dict) else best.seeders

        torrent_hash = extract_info_hash_from_url(best_magnet_url) or extract_info_hash_from_url(best_download_url)
        if not torrent_hash:
            logger.error(
                "Could not derive info hash for '%s' from magnet=%r or url=%r — leaving WANTED",
                book.title,
                best_magnet_url,
                best_download_url,
            )
            if not self._transition_book(book, BookStatus.WANTED):
                logger.warning("Could not transition '%s' back to WANTED", book.title)
            db.commit()
            return 0

        # Duplicate-Download guard: if an active download already exists for this book,
        # skip creating a new one. Advance the book to GRABBED if it is still SEARCHING.
        existing_active = (
            db.query(Download)
            .filter(
                Download.book_id == book.id,
                Download.status.in_([DownloadStatus.QUEUED.value, DownloadStatus.DOWNLOADING.value]),
            )
            .first()
        )
        if existing_active is not None:
            logger.info(
                "Download already exists for '%s' (id=%d, hash=%s, status=%s) — skipping new grab",
                book.title,
                existing_active.id,
                existing_active.torrent_hash,
                existing_active.status,
            )
            if book.status == BookStatus.SEARCHING:
                if self._transition_book(book, BookStatus.GRABBED, download=existing_active):
                    db.commit()
                else:
                    db.commit()
            else:
                db.commit()
            return 0

        download = Download(
            book_id=book.id,
            torrent_hash=torrent_hash,
            torrent_name=best_title or book.title,
            indexer_name=best_indexer or "unknown",
            download_url=best_download_url or best_magnet_url or "",
            size=best_size or 0,
            seeders=best_seeders or 0,
            status=DownloadStatus.QUEUED,
        )
        db.add(download)

        # Force UNIQUE(torrent_hash) check before book transition. Concurrent grabs
        # of the same torrent will land here — one wins, the other adopts the existing row.
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
            if existing is not None:
                logger.info(
                    "Race detected: torrent_hash %s already grabbed (Download id=%d, book_id=%d) — adopting",
                    torrent_hash,
                    existing.id,
                    existing.book_id,
                )
                if existing.book_id == book.id and book.status == BookStatus.SEARCHING:
                    if self._transition_book(book, BookStatus.GRABBED, download=existing):
                        db.commit()
                    else:
                        db.commit()
            else:
                logger.warning(
                    "IntegrityError adding Download for '%s' but no existing row found", book.title
                )
            return 0

        if not self._transition_book(book, BookStatus.GRABBED, download=download):
            logger.warning(f"Could not transition '{book.title}' SEARCHING→GRABBED")
            db.rollback()
            return 0

        db.commit()
        logger.info(f"Grabbed '{book.title}' from {download.indexer_name} (hash={download.torrent_hash})")
        log_event(
            "book_grabbed",
            book_id=book.id,
            indexer=download.indexer_name,
            seeders=download.seeders or 0,
            size=download.size or 0,
        )
        return 1

    def _fail_book(self, book: Book, db: Any, reason: str = "Pipeline book failure") -> None:
        try:
            if self._transition_book(book, BookStatus.FAILED):
                db.commit()
                self._broadcast(
                    "book_failed",
                    {"book_id": book.id, "title": book.title, "reason": reason},
                )
                log_event(
                    "book_failed",
                    book_id=book.id,
                    reason=book.failure_reason or reason,
                    stage="pipeline",
                )
        except Exception as exc:
            logger.error(f"Could not fail book '{book.title}': {exc}")
            db.rollback()

    def _fail_download(self, download: Download, db: Any, reason: str = "") -> None:
        try:
            download.error_message = reason
            if transition_download(download, DownloadStatus.FAILED):
                db.commit()
                self._broadcast(
                    "download_failed",
                    {"book_id": download.book_id, "download_id": download.id, "reason": reason},
                )
        except Exception as exc:
            logger.error(f"Could not fail download {download.id}: {exc}")
            db.rollback()

    def _broadcast(self, event: str, data: dict[str, Any]) -> None:
        if self.ws_manager:
            self.ws_manager.broadcast_sync(event, data)

    def _transition_book(
        self,
        book: Book,
        target_status: str,
        *,
        download: Download | None = None,
    ) -> bool:
        old_status = book.status
        if not transition_book(book, target_status):
            return False

        self._broadcast(
            "book_status_changed",
            {
                "book_id": book.id,
                "old_status": old_status,
                "new_status": book.status,
                "title": book.title,
            },
        )

        if target_status == BookStatus.SEARCHING:
            self._broadcast(
                "book_searching",
                {
                    "book_id": book.id,
                    "title": book.title,
                    "attempt": (book.search_attempts or 0) + 1,
                },
            )
        elif target_status == BookStatus.GRABBED:
            self._broadcast(
                "book_grabbed",
                {
                    "book_id": book.id,
                    "title": book.title,
                    "release_title": download.torrent_name if download else book.title,
                    "indexer": download.indexer_name if download else None,
                },
            )
        elif target_status == BookStatus.DOWNLOADING:
            self._broadcast(
                "download_started",
                {
                    "book_id": book.id,
                    "download_id": download.id if download else None,
                    "title": book.title,
                },
            )
        elif target_status == BookStatus.IMPORTING:
            self._broadcast(
                "download_completed",
                {
                    "book_id": book.id,
                    "download_id": download.id if download else None,
                    "file_path": download.file_path if download else None,
                },
            )
        elif target_status == BookStatus.IN_LIBRARY:
            self._broadcast(
                "import_completed",
                {
                    "book_id": book.id,
                    "title": book.title,
                    "file_path": download.file_path if download else book.file_path,
                },
            )

        return True
