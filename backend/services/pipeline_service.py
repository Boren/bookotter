# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""
Pipeline orchestrator: WANTED → SEARCHING → GRABBED → DOWNLOADING → IMPORTING → IN_LIBRARY.

The recurring scheduler (start_monitoring) only advances post-grab stages.
See run_pipeline() for the rationale.
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.database import SessionLocal
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_states import transition_book, transition_download
from backend.services.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

PIPELINE_INTERVAL_SECONDS = 15


def _guid_to_hash(guid: str | None) -> str:
    raw = guid or str(datetime.now(UTC).timestamp())
    return hashlib.md5(raw.encode()).hexdigest()


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
    ):
        self.search_service = search_service
        self.download_service = download_service
        self.import_service = import_service
        self._session_factory = db_session_factory or SessionLocal
        self._scheduler: AsyncIOScheduler | None = None
        self.ws_manager = ws_manager

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

    def run_pipeline(self) -> dict[str, int]:
        # Pre-grab search stages are intentionally absent - searches are user-initiated
        # (search.py routes, /api/wanted/search-all) or future RSS sync, never on a timer.
        logger.debug("Pipeline run starting (post-grab stages only)")
        results: dict[str, int] = {}
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
        logger.debug(f"Pipeline run complete: {results}")
        return results

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
        self._scheduler.start()
        logger.info(f"Pipeline monitoring started (interval={PIPELINE_INTERVAL_SECONDS}s)")

    def stop_monitoring(self) -> None:
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Pipeline monitoring stopped")

    def _search_and_grab(self, book: Book, db: Any) -> int:
        author_name = book.author.name if book.author else ""

        if book.status in {BookStatus.WANTED, BookStatus.MISSING}:
            if not self._transition_book(book, BookStatus.SEARCHING):
                logger.warning(f"Could not transition '{book.title}' to SEARCHING from {book.status}, skipping")
                return 0

        book.search_attempts = (book.search_attempts or 0) + 1
        book.last_searched_at = datetime.now(UTC)
        db.commit()

        results = self.search_service.search_book(book.title, author_name)
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
        best_guid = best.get("guid") if isinstance(best, dict) else best.guid
        best_title = best.get("title") if isinstance(best, dict) else best.title
        best_indexer = best.get("indexer") if isinstance(best, dict) else best.indexer
        best_download_url = best.get("download_url") if isinstance(best, dict) else best.download_url
        best_magnet_url = best.get("magnet_url") if isinstance(best, dict) else best.magnet_url
        best_size = best.get("size") if isinstance(best, dict) else best.size
        best_seeders = best.get("seeders") if isinstance(best, dict) else best.seeders

        download = Download(
            book_id=book.id,
            torrent_hash=_guid_to_hash(best_guid),
            torrent_name=best_title or book.title,
            indexer_name=best_indexer or "unknown",
            download_url=best_download_url or best_magnet_url or "",
            size=best_size or 0,
            seeders=best_seeders or 0,
            status=DownloadStatus.QUEUED,
        )
        db.add(download)

        if not self._transition_book(book, BookStatus.GRABBED, download=download):
            logger.warning(f"Could not transition '{book.title}' SEARCHING→GRABBED")
            db.rollback()
            return 0

        db.commit()
        logger.info(f"Grabbed '{book.title}' from {download.indexer_name} (hash={download.torrent_hash})")
        return 1

    def _fail_book(self, book: Book, db: Any, reason: str = "Pipeline book failure") -> None:
        try:
            if self._transition_book(book, BookStatus.FAILED):
                db.commit()
                self._broadcast(
                    "book_failed",
                    {"book_id": book.id, "title": book.title, "reason": reason},
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
