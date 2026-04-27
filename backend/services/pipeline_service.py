"""
Pipeline orchestrator: WANTED → SEARCHING → GRABBED → DOWNLOADING → IMPORTING → IN_LIBRARY.

Each stage method runs every 15 seconds via APScheduler (start_monitoring).
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
    ):
        self.search_service = search_service
        self.download_service = download_service
        self.import_service = import_service
        self._session_factory = db_session_factory or SessionLocal
        self._scheduler: AsyncIOScheduler | None = None

    def process_wanted_books(self) -> int:
        if self.search_service is None:
            logger.warning("process_wanted_books: no search_service configured, skipping")
            return 0

        db = self._session_factory()
        grabbed = 0
        try:
            books = db.query(Book).filter(Book.status == BookStatus.WANTED).all()
            logger.debug(f"process_wanted_books: {len(books)} WANTED book(s) found")
            for book in books:
                try:
                    grabbed += self._search_and_grab(book, db)
                except Exception as exc:
                    logger.error(f"Unexpected error processing WANTED book '{book.title}': {exc}")
                    self._fail_book(book, db)
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
                    self._fail_book(book, db)
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
                    self._fail_book(book, db)
                    continue
                download = queued[0]
                try:
                    success = self.download_service.add_torrent(download)
                    if success:
                        if transition_download(download, DownloadStatus.DOWNLOADING):
                            db.commit()
                        if transition_book(book, BookStatus.DOWNLOADING):
                            db.commit()
                        started += 1
                        logger.info(f"Download started for '{book.title}'")
                    else:
                        logger.warning(f"add_torrent returned False for '{book.title}'")
                        self._fail_download(download, db, "add_torrent returned False")
                        self._fail_book(book, db)
                except Exception as exc:
                    logger.error(f"Error adding torrent for '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db)
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
                    self._fail_book(book, db)
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
                    if transition_book(book, BookStatus.IMPORTING):
                        db.commit()
                    importing += 1
                    logger.info(f"Download complete for '{book.title}': {file_path}")
                except Exception as exc:
                    logger.error(f"Error checking download for '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db)
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
                    self._fail_book(book, db)
                    continue
                download = completed[0]
                if not download.file_path:
                    logger.warning(f"Download for '{book.title}' has no file_path — failing")
                    self._fail_download(download, db, "No file path recorded after download")
                    self._fail_book(book, db)
                    continue
                try:
                    success = self.import_service.import_epub(book, download.file_path)
                    if success:
                        if transition_download(download, DownloadStatus.IMPORTING):
                            db.commit()
                        if transition_download(download, DownloadStatus.IMPORTED):
                            db.commit()
                        if transition_book(book, BookStatus.IN_LIBRARY):
                            db.commit()
                        imported += 1
                        logger.info(f"Imported '{book.title}' to library")
                    else:
                        logger.warning(f"import_epub returned False for '{book.title}'")
                        self._fail_download(download, db, "import_epub returned False")
                        self._fail_book(book, db)
                except Exception as exc:
                    logger.error(f"Error importing '{book.title}': {exc}")
                    self._fail_download(download, db, str(exc))
                    self._fail_book(book, db)
            return imported
        finally:
            db.close()

    def run_pipeline(self) -> dict[str, int]:
        logger.info("Pipeline run starting")
        results: dict[str, int] = {}
        for stage_name, method in [
            ("wanted", self.process_wanted_books),
            ("searching", self.process_searching_books),
            ("grabbed", self.process_grabbed_books),
            ("downloading", self.process_downloading_books),
            ("importing", self.process_importing_books),
        ]:
            try:
                results[stage_name] = method()
            except Exception as exc:
                logger.error(f"Pipeline stage '{stage_name}' raised: {exc}")
                results[stage_name] = 0
        logger.info(f"Pipeline run complete: {results}")
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

        if book.status == BookStatus.WANTED:
            if not transition_book(book, BookStatus.SEARCHING):
                logger.warning(f"Could not transition '{book.title}' WANTED→SEARCHING, skipping")
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
            if not transition_book(book, BookStatus.WANTED):
                logger.warning(f"Could not transition '{book.title}' back to WANTED, leaving in current state")
            db.commit()
            return 0

        best = results[0]
        download = Download(
            book_id=book.id,
            torrent_hash=_guid_to_hash(best.get("guid")),
            torrent_name=best.get("title") or book.title,
            indexer_name=best.get("indexer") or "unknown",
            download_url=best.get("download_url") or best.get("magnet_url") or "",
            size=best.get("size") or 0,
            seeders=best.get("seeders") or 0,
            status=DownloadStatus.QUEUED,
        )
        db.add(download)

        if not transition_book(book, BookStatus.GRABBED):
            logger.warning(f"Could not transition '{book.title}' SEARCHING→GRABBED")
            db.rollback()
            return 0

        db.commit()
        logger.info(f"Grabbed '{book.title}' from {download.indexer_name} (hash={download.torrent_hash})")
        return 1

    def _fail_book(self, book: Book, db: Any) -> None:
        try:
            if transition_book(book, BookStatus.FAILED):
                db.commit()
        except Exception as exc:
            logger.error(f"Could not fail book '{book.title}': {exc}")
            db.rollback()

    def _fail_download(self, download: Download, db: Any, reason: str = "") -> None:
        try:
            download.error_message = reason
            if transition_download(download, DownloadStatus.FAILED):
                db.commit()
        except Exception as exc:
            logger.error(f"Could not fail download {download.id}: {exc}")
            db.rollback()
