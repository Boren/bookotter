# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""
Pipeline orchestrator: WANTED → SEARCHING → GRABBED → DOWNLOADING → IMPORTING → IN_LIBRARY.

The recurring scheduler (start_monitoring) only advances post-grab stages.
See run_pipeline() for the rationale.
"""

import logging
import os
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
from backend.services.search_service import ScoredResult
from backend.services.torrent_hash import extract_info_hash_from_url, fetch_and_hash_torrent
from backend.services.websocket_manager import WebSocketManager
from backend.utils.cleanup import cleanup_orphan_tmp_files
from backend.utils.events import log_event
from backend.utils.failure import _append_failure_history
from backend.utils.pipeline_lock import acquire_pipeline_lock
from backend.utils.transfer_progress import make_progress_callback

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

    def search_single_book(self, book_id: int) -> int:
        """Search and grab one WANTED/MISSING book (used by search-on-add for manual adds)."""
        if self.search_service is None:
            logger.warning("search_single_book: no search_service configured, skipping")
            return 0

        db = self._session_factory()
        try:
            book = db.get(Book, book_id)
            if book is None:
                logger.warning(f"search_single_book: book {book_id} not found")
                return 0
            if book.status not in {BookStatus.WANTED, BookStatus.MISSING}:
                logger.debug(f"search_single_book: book {book_id} in status {book.status!r}, skipping")
                return 0
            try:
                return self._search_and_grab(book, db)
            except Exception as exc:
                logger.error(f"Unexpected error searching book '{book.title}': {exc}")
                self._fail_book(book, db, str(exc))
                return 0
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
                        if not transition_download(download, DownloadStatus.DOWNLOADING, db):
                            logger.warning("Could not transition download %s to DOWNLOADING", download.id)
                            db.rollback()
                            continue
                        if not self._transition_book(book, BookStatus.DOWNLOADING, db=db, download=download):
                            logger.warning("Could not transition '%s' to DOWNLOADING", book.title)
                            db.rollback()
                            continue
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
                    if not transition_download(download, DownloadStatus.COMPLETED, db):
                        logger.warning("Could not transition download %s to COMPLETED", download.id)
                        db.rollback()
                        continue
                    if not self._transition_book(book, BookStatus.IMPORTING, db=db, download=download):
                        logger.warning("Could not transition '%s' to IMPORTING", book.title)
                        db.rollback()
                        continue
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

        from backend.config import get_first_real_kindle, load_config

        config_for_pipeline = load_config()
        auto_kindle = config_for_pipeline.get("pipeline", {}).get("kindle_sync_on_import", True)
        real_kindle = get_first_real_kindle(config_for_pipeline) if auto_kindle else None

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
                    db.refresh(book)
                    if success:
                        if book.status != BookStatus.IN_LIBRARY.value:
                            logger.warning(
                                "ImportService claimed success but book %d has status=%r — failing",
                                book.id,
                                book.status,
                            )
                            self._fail_download(download, db, "Import success but book status mismatched")
                            self._fail_book(book, db, "Import success but book status mismatched")
                            continue
                        if not transition_download(download, DownloadStatus.IMPORTING, db):
                            logger.warning("Could not transition download %s to IMPORTING", download.id)
                            db.rollback()
                            continue
                        if not transition_download(download, DownloadStatus.IMPORTED, db):
                            logger.warning("Could not transition download %s to IMPORTED", download.id)
                            db.rollback()
                            continue
                        if real_kindle is not None:
                            book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
                            book.kindle_first_pending_at = datetime.utcnow()
                        db.commit()
                        imported += 1
                        logger.info(f"Imported '{book.title}' to library")
                    else:
                        logger.warning(f"import_epub returned False for '{book.title}'")
                        if book.status != BookStatus.FAILED.value:
                            self._fail_download(download, db, "import_epub returned False")
                            self._fail_book(book, db, "import_epub returned False")
                except Exception as exc:
                    logger.error(f"Error importing '{book.title}': {exc}")
                    try:
                        db.refresh(book)
                    except Exception:
                        pass
                    if book.status != BookStatus.FAILED.value:
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
                    _append_failure_history(book, FailureReason.RETRY_BUDGET_EXHAUSTED.value)
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

                if book.failure_reason:
                    _append_failure_history(book, book.failure_reason)
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
        """Return the first user-configured (non-placeholder) Kindle config, or None.

        Reads YAML on every call so Settings UI changes take effect on the next
        pipeline cycle without an app restart.
        """
        from backend.config import get_first_real_kindle

        return get_first_real_kindle()

    def _load_config_for_delivery(self) -> dict:
        """Indirection so tests can override config loading without monkeypatching the module."""
        from backend.config import load_config

        return load_config()

    def process_kindle_delivery_books(self) -> int:
        """Drive the Kindle delivery state machine.

        Bookkeeping (always runs, pure DB — works while the Kindle is off):
            - Stamp kindle_first_pending_at if missing.
            - If now - first_pending_at > KINDLE_DELIVERY_TIMEOUT_DAYS → SKIPPED.

        Reachability gate: one cheap TCP probe per cycle, only when there is
        deliverable or re-armable work. Unreachable → skip all SSH work this
        cycle without touching per-book attempt counters (the Kindle is off
        most of the time; hammering it with per-book connections is pointless).

        PENDING (Kindle reachable):
            - Resolve absolute path and attempt SFTP transfer:
                result["success"] is True → DELIVERED (kindle_delivery_attempts++)
                result["success"] is False → stays PENDING (attempts++)
                exception → stays PENDING (attempts++)

        SKIPPED (Kindle reachable):
            - Re-arm as PENDING with a fresh kindle_first_pending_at
              (auto-recover; the probe already proved reachability).

        Returns:
            Number of PENDING books that reached a terminal state
            (DELIVERED or SKIPPED) during this run.
        """
        from backend.clients.kindle_client import KindleClient
        from backend.constants import KINDLE_DELIVERY_TIMEOUT_DAYS

        kindle_config = self._get_kindle_config()
        if kindle_config is None:
            logger.debug("process_kindle_delivery_books: no real kindle configured, skipping")
            return 0

        # Build KindleClient lazily from fresh config so Settings UI changes take effect
        # on the next pipeline cycle without an app restart. Tests inject a mock via the
        # constructor's `kindle_client=` parameter.
        kindle_client = self.kindle_client or KindleClient.from_config(kindle_config)

        config = self._load_config_for_delivery()
        folder_org = config.get("transfer", {}).get("folder_organization", "flat")

        db = self._session_factory()
        now = datetime.utcnow()
        timeout = timedelta(days=KINDLE_DELIVERY_TIMEOUT_DAYS)
        processed = 0

        try:
            # Snapshot SKIPPED *before* mutating PENDING so a freshly-timed-out
            # book is not immediately re-armed by the auto-retry loop in the
            # same call (would create a PENDING↔SKIPPED bounce).
            skipped_books = (
                db.query(Book).filter(Book.kindle_delivery_status == KindleDeliveryStatus.SKIPPED.value).all()
            )
            pending_books = (
                db.query(Book).filter(Book.kindle_delivery_status == KindleDeliveryStatus.PENDING.value).all()
            )

            # Bookkeeping pass: pure DB work that must keep ticking while the
            # Kindle is off (waiting-since stamps and the 14-day timeout).
            deliverable: list[tuple[Book, str]] = []
            for book in pending_books:
                if book.kindle_first_pending_at is None:
                    book.kindle_first_pending_at = now

                if (now - book.kindle_first_pending_at) > timeout:
                    book.kindle_delivery_status = KindleDeliveryStatus.SKIPPED.value
                    logger.info("Kindle delivery timed out for book %s — marking SKIPPED", book.id)
                    self._broadcast("kindle_delivery_skipped", {"book_id": book.id})
                    processed += 1
                    continue

                if book.root_folder is None or not book.file_path:
                    logger.warning(
                        "Kindle delivery: book %s has no root_folder or file_path — leaving PENDING",
                        book.id,
                    )
                    continue
                abs_path = os.path.join(str(book.root_folder.path), str(book.file_path))
                if not os.path.exists(abs_path):
                    logger.warning(
                        "Kindle delivery: file missing for book %s at %s — leaving PENDING",
                        book.id,
                        abs_path,
                    )
                    continue
                deliverable.append((book, abs_path))

            # Single reachability probe per cycle; skip it entirely on idle
            # cycles so a configured-but-off Kindle costs zero network traffic.
            if not deliverable and not skipped_books:
                db.commit()
                return processed
            if not kindle_client.is_reachable():
                logger.debug("Kindle unreachable — skipping delivery stage this cycle")
                db.commit()
                return processed

            for book, abs_path in deliverable:
                book.kindle_delivery_status = KindleDeliveryStatus.IN_PROGRESS.value
                book.kindle_delivery_attempts = (book.kindle_delivery_attempts or 0) + 1
                db.commit()
                self._broadcast("kindle_delivery_started", {"book_id": book.id, "book_title": book.title})

                author_name = book.author.name if book.author else ""
                series_name = str(book.series_name) if book.series_name else ""
                transfer_start = time.monotonic()
                progress_cb = make_progress_callback(
                    self._broadcast,
                    "kindle_delivery_progress",
                    {"book_id": book.id, "book_title": book.title},
                )

                try:
                    result = kindle_client.transfer_file(
                        local_path=abs_path,
                        skip_existing=True,
                        author=author_name,
                        series=series_name,
                        folder_organization=folder_org,
                        progress_callback=progress_cb,
                    )
                except Exception as exc:
                    logger.warning("Kindle delivery raised for book %s: %s", book.id, exc)
                    book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
                    db.commit()
                    continue

                if result.get("success"):
                    book.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
                    book.kindle_delivered_at = datetime.utcnow()
                    duration_ms = int((time.monotonic() - transfer_start) * 1000)
                    logger.info(
                        "Kindle delivery DELIVERED for book %s (%s, %d bytes)",
                        book.id,
                        result.get("status", "transferred"),
                        result.get("file_size", 0),
                    )
                    log_event(
                        "kindle_delivered",
                        book_id=book.id,
                        duration_ms=duration_ms,
                        size_bytes=result.get("file_size", 0),
                    )
                    self._broadcast(
                        "kindle_delivered",
                        {"book_id": book.id, "status": result.get("status", "transferred")},
                    )
                    processed += 1
                else:
                    logger.warning(
                        "Kindle delivery soft-failed for book %s: %s",
                        book.id,
                        result.get("error", "unknown"),
                    )
                    book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
                db.commit()

            # The probe above already proved reachability — re-arm without
            # opening any further SSH connections.
            for book in skipped_books:
                book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
                book.kindle_first_pending_at = now
                self._broadcast("kindle_delivery_requeued", {"book_id": book.id})
            db.commit()
            return processed
        finally:
            db.close()

    def kick_kindle_delivery(self) -> dict[str, Any]:
        """Run only the Kindle delivery stage, right now.

        Called in the background after a user queues a book so delivery starts
        within seconds instead of waiting for the next scheduled tick. Never
        raises: if the pipeline lock is held or a bulk Kindle sync is running,
        it defers silently — the book is already PENDING and the 15s scheduler
        tick will deliver it.
        """
        from backend.api.routes.sync import is_kindle_sync_running

        if is_kindle_sync_running():
            logger.info("Kindle kick skipped: bulk Kindle sync in progress")
            return {"skipped": True, "reason": "bulk_sync_running"}

        db = self._session_factory()
        try:
            try:
                with acquire_pipeline_lock(db, holder="kindle_kick"):
                    delivered = self.process_kindle_delivery_books()
                    return {"kindle_delivery": delivered}
            except PipelineError as exc:
                if exc.reason == FailureReason.PIPELINE_LOCK_HELD:
                    logger.info("Kindle kick skipped: pipeline lock held: %s", exc)
                    return {"skipped": True, "reason": "lock_held"}
                raise
        except Exception as exc:
            logger.warning("Kindle kick failed: %s", exc)
            return {"skipped": True, "reason": "error"}
        finally:
            try:
                db.close()
            except Exception as exc:
                logger.debug(f"Error closing kindle kick lock session: {exc}")

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
                        ("kindle_delivery", self.process_kindle_delivery_books),
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
                        kindle_delivery=results.get("kindle_delivery", 0),
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
        if self.search_service is None:
            logger.warning("_search_and_grab: no search_service configured, skipping")
            return 0

        author_name = book.author.name if book.author else ""

        if book.status in {BookStatus.WANTED, BookStatus.MISSING}:
            if not self._transition_book(book, BookStatus.SEARCHING, db=db):
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
            if not self._transition_book(book, BookStatus.WANTED, db=db):
                logger.warning(f"Could not transition '{book.title}' back to WANTED, leaving in current state")
                db.rollback()
                return 0
            db.commit()
            return 0

        approved_results = [result for result in results if getattr(result, "approved", True)]
        if not approved_results:
            logger.info(
                f"No approved results for '{book.title}' — returning to WANTED for retry (attempt {book.search_attempts})"
            )
            if not self._transition_book(book, BookStatus.WANTED, db=db):
                logger.warning(f"Could not transition '{book.title}' back to WANTED, leaving in current state")
                db.rollback()
                return 0
            db.commit()
            return 0

        best = approved_results[0]
        if isinstance(best, dict):
            best = ScoredResult(
                guid=best.get("guid"),
                indexer_id=best.get("indexer_id"),
                indexer=best.get("indexer"),
                title=best.get("title"),
                size=best.get("size"),
                seeders=best.get("seeders"),
                leechers=best.get("leechers"),
                download_url=best.get("download_url"),
                magnet_url=best.get("magnet_url"),
                publish_date=best.get("publish_date"),
                protocol=best.get("protocol"),
                categories=best.get("categories") or [],
                age_days=best.get("age_days") or 0.0,
                title_similarity=best.get("title_similarity") or 1.0,
                author_match=best.get("author_match", False),
                rejections=best.get("rejections") or [],
                approved=best.get("approved", True),
            )

        return self.grab_known_result(book, best, db)

    def grab_known_result(self, book: Book, scored_result: ScoredResult, db: Any) -> int:
        if scored_result.approved is not True:
            return 0

        if book.status in {BookStatus.WANTED, BookStatus.MISSING}:
            if not self._transition_book(book, BookStatus.SEARCHING, db=db):
                logger.warning(f"Could not transition '{book.title}' to SEARCHING from {book.status}, skipping")
                return 0

            book.search_attempts = (book.search_attempts or 0) + 1
            book.last_searched_at = datetime.now(UTC)
        elif book.status != BookStatus.SEARCHING:
            logger.warning("Cannot grab known result for '%s' from status %s", book.title, book.status)
            return 0

        torrent_hash = extract_info_hash_from_url(scored_result.magnet_url) or extract_info_hash_from_url(
            scored_result.download_url
        )
        if not torrent_hash:
            # Private trackers serve .torrent files instead of magnets — fetch the
            # file to compute the real info hash (and spool it for qBittorrent).
            torrent_hash = fetch_and_hash_torrent(scored_result.download_url)
        if not torrent_hash:
            logger.error(
                "Could not derive info hash for '%s' from magnet=%r or url=%r — leaving WANTED",
                book.title,
                scored_result.magnet_url,
                scored_result.download_url,
            )
            if not self._transition_book(book, BookStatus.WANTED, db=db):
                logger.warning("Could not transition '%s' back to WANTED", book.title)
                db.rollback()
                return 0
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
                if self._transition_book(book, BookStatus.GRABBED, db=db, download=existing_active):
                    db.commit()
                else:
                    db.rollback()
            else:
                db.commit()
            return 0

        download = Download(
            book_id=book.id,
            torrent_hash=torrent_hash,
            torrent_name=scored_result.title or book.title,
            indexer_name=scored_result.indexer or "unknown",
            download_url=scored_result.download_url or scored_result.magnet_url or "",
            size=scored_result.size or 0,
            seeders=scored_result.seeders or 0,
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
                    if self._transition_book(book, BookStatus.GRABBED, db=db, download=existing):
                        db.commit()
                    else:
                        db.rollback()
            else:
                logger.warning("IntegrityError adding Download for '%s' but no existing row found", book.title)
            return 0

        if not self._transition_book(book, BookStatus.GRABBED, db=db, download=download):
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
            if self._transition_book(book, BookStatus.FAILED, db=db):
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
            else:
                db.rollback()
        except Exception as exc:
            logger.error(f"Could not fail book '{book.title}': {exc}")
            db.rollback()

    def _fail_download(self, download: Download, db: Any, reason: str = "") -> None:
        try:
            download.error_message = reason
            if transition_download(download, DownloadStatus.FAILED, db):
                db.commit()
                self._broadcast(
                    "download_failed",
                    {"book_id": download.book_id, "download_id": download.id, "reason": reason},
                )
            else:
                db.rollback()
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
        db: Any,
        *,
        download: Download | None = None,
    ) -> bool:
        old_status = book.status
        if not transition_book(book, target_status, db):
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
