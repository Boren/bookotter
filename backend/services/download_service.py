# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOperatorIssue=false, reportOptionalMemberAccess=false
"""
Download Monitor Service
Manages the qBittorrent torrent lifecycle for book downloads.

Responsibilities:
- Add torrents to qBittorrent and create Download DB records
- Monitor download progress and detect completion
- Handle multi-file torrents: skip non-EPUB files
- Reconcile DB state with qBit state on app startup
"""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from backend.clients.qbittorrent_client import (
    DOWNLOAD_COMPLETE_STATES,
    QBittorrentClient,
    TorrentState,
)
from backend.constants import DOWNLOAD_STALL_THRESHOLD_MIN, DOWNLOAD_TOTAL_TIMEOUT_HOURS
from backend.errors import FailureReason
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_states import transition_book, transition_download
from backend.services.torrent_hash import extract_info_hash_from_url
from backend.services.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

# How long to wait after adding a torrent before querying file list
# qBit needs a moment to parse the torrent metadata
POST_ADD_DELAY_SECONDS = 1.0

DEFAULT_CATEGORY = "books"

ACTIVE_DL_STATES = {
    TorrentState.DOWNLOADING,
    TorrentState.STALLED_DL,
    TorrentState.CHECKING_DL,
    TorrentState.MOVING,
}

QUEUED_DL_STATES = {
    TorrentState.QUEUED_DL,
    TorrentState.PAUSED_DL,
}


class DownloadService:
    """
    Manages torrent downloads via qBittorrent and tracks them in the database.

    Constructor args:
        qbit_client:        Fully initialised QBittorrentClient instance.
        db_session_factory: Zero-argument callable that returns a new SQLAlchemy Session.
        category:           qBittorrent category label to apply to book torrents.
    """

    def __init__(
        self,
        qbit_client: QBittorrentClient,
        db_session_factory,
        category: str = DEFAULT_CATEGORY,
        ws_manager: WebSocketManager | None = None,
    ) -> None:
        self.qbit = qbit_client
        self._db_factory = db_session_factory
        self.category = category
        self.ws_manager = ws_manager

    def add_download(self, book_id: int, search_result: dict) -> "Download | None":
        """
        Add a torrent to qBittorrent and create a Download DB record.

        Handles multi-file torrents by setting priority 0 on all non-EPUB files
        immediately after the torrent is added.

        Args:
            book_id:       The Book.id to associate the download with.
            search_result: Normalised search result dict from ProwlarrClient, containing:
                           - magnet_url (required — needed to derive the info hash)
                           - download_url (fallback torrent URL)
                           - title, indexer, size, seeders

        Returns:
            The created Download model instance, or None on failure.
        """
        magnet_url: str | None = search_result.get("magnet_url")
        download_url: str | None = search_result.get("download_url")

        if not magnet_url and not download_url:
            logger.error("No URL available in search result for book %d", book_id)
            return None

        torrent_hash = extract_info_hash_from_url(magnet_url) if magnet_url else None
        if not torrent_hash:
            logger.error(
                "Could not determine torrent hash for book %d — a magnet URL is required",
                book_id,
            )
            return None

        url_to_add = magnet_url or download_url

        # Pre-flight DB dedup: skip if an active download for this book already exists
        # or if any download with this torrent_hash is already tracked.
        db = self._db_factory()
        try:
            existing_for_book = (
                db.query(Download)
                .filter(
                    Download.book_id == book_id,
                    Download.status.in_([DownloadStatus.QUEUED.value, DownloadStatus.DOWNLOADING.value]),
                )
                .first()
            )
            if existing_for_book is not None:
                logger.info(
                    "Active download already exists for book %d (id=%d, hash=%s...) — skipping",
                    book_id,
                    existing_for_book.id,
                    (existing_for_book.torrent_hash or "?")[:16],
                )
                db.expunge(existing_for_book)
                return existing_for_book

            existing_by_hash = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
            if existing_by_hash is not None:
                logger.info(
                    "Torrent hash %s... already tracked (Download id=%d, book %d) — skipping",
                    torrent_hash[:16],
                    existing_by_hash.id,
                    existing_by_hash.book_id,
                )
                db.expunge(existing_by_hash)
                return existing_by_hash
        finally:
            db.close()

        # Orphan adoption: if the torrent already lives in qBit (e.g. survivor of a
        # previous run), reuse it instead of re-adding (which qBit would silently no-op).
        is_orphan = self.qbit.get_torrent_properties(torrent_hash) is not None
        if is_orphan:
            logger.info(
                "Adopting orphan torrent %s... already present in qBit for book %d",
                torrent_hash[:16],
                book_id,
            )
        else:
            self.qbit.ensure_category_exists(self.category)
            success = self.qbit.add_torrent(url_to_add, category=self.category)
            if not success:
                logger.error("qBittorrent rejected torrent for book %d", book_id)
                return None

            time.sleep(POST_ADD_DELAY_SECONDS)

        epub_file_name = self._configure_file_priorities(torrent_hash)

        db = self._db_factory()
        try:
            download = Download(
                book_id=book_id,
                torrent_hash=torrent_hash,
                torrent_name=search_result.get("title") or "Unknown",
                indexer_name=search_result.get("indexer") or "Unknown",
                download_url=url_to_add,
                size=search_result.get("size") or 0,
                seeders=search_result.get("seeders") or 0,
                status=DownloadStatus.QUEUED.value,
                file_path=epub_file_name,
            )
            db.add(download)

            # Force UNIQUE(torrent_hash) check before transitioning the book so a
            # concurrent insert can be detected and adopted gracefully.
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                existing = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
                if existing is not None:
                    logger.info(
                        "Race: torrent_hash %s... already inserted — adopting Download id=%d",
                        torrent_hash[:16],
                        existing.id,
                    )
                    db.expunge(existing)
                    return existing
                logger.warning("IntegrityError but no existing Download row found for hash %s", torrent_hash)
                return None

            book = db.query(Book).filter(Book.id == book_id).first()
            if book:
                if not self._transition_book(book, BookStatus.GRABBED, download=download):
                    logger.warning(
                        "Could not transition book %d from %r → grabbed",
                        book_id,
                        book.status,
                    )
            else:
                logger.warning("Book %d not found in DB when adding download", book_id)

            db.commit()
            db.refresh(download)
            logger.info(
                "Created Download record for book %d: torrent=%s... (orphan=%s)",
                book_id,
                torrent_hash[:16],
                is_orphan,
            )
            return download

        except Exception as exc:
            db.rollback()
            logger.error("Failed to save Download record for book %d: %s", book_id, exc)
            return None
        finally:
            db.close()

    def monitor_downloads(self) -> int:
        """
        Poll qBittorrent for active downloads and update DB status.

        Intended to be called periodically (e.g. every 15 s by APScheduler).
        Detects completion and calls handle_completed for finished torrents.

        Returns:
            Number of active downloads examined.
        """
        db = self._db_factory()
        try:
            active_statuses = [DownloadStatus.QUEUED.value, DownloadStatus.DOWNLOADING.value]
            downloads = db.query(Download).filter(Download.status.in_(active_statuses)).all()

            if not downloads:
                return 0

            torrents = self.qbit.get_torrents(category=self.category)
            torrent_map: dict[str, dict] = {t["hash"]: t for t in torrents}

            processed = 0
            for download in downloads:
                torrent_info = torrent_map.get(download.torrent_hash)
                if not torrent_info:
                    logger.warning(
                        "Torrent %s... not found in qBit (Download id=%d)",
                        download.torrent_hash[:16],
                        download.id,
                    )
                    processed += 1
                    continue

                self._update_progress_tracking(download, torrent_info)
                if self._check_stall_and_timeout(download, db):
                    processed += 1
                    continue

                state = torrent_info.get("state", TorrentState.UNKNOWN)
                progress = torrent_info.get("progress", 0.0)
                is_complete = state in DOWNLOAD_COMPLETE_STATES or progress >= 1.0

                if is_complete and download.status == DownloadStatus.DOWNLOADING.value:
                    logger.info("Download completed: %r (id=%d)", download.torrent_name, download.id)
                    self.handle_completed(download, db=db)

                elif state == TorrentState.ERROR or state == TorrentState.MISSING_FILES:
                    if transition_download(download, DownloadStatus.FAILED):
                        download.error_message = f"Torrent in error state ({state})"
                        logger.warning(
                            "Download errored in qBit: %r (id=%d, state=%s)",
                            download.torrent_name,
                            download.id,
                            state,
                        )
                        self._broadcast(
                            "download_failed",
                            {
                                "book_id": download.book_id,
                                "download_id": download.id,
                                "reason": download.error_message,
                            },
                        )

                elif state in ACTIVE_DL_STATES and download.status == DownloadStatus.QUEUED.value:
                    transition_download(download, DownloadStatus.DOWNLOADING)
                    book = db.query(Book).filter(Book.id == download.book_id).first()
                    if book:
                        self._transition_book(book, BookStatus.DOWNLOADING, download=download)

                if state in ACTIVE_DL_STATES:
                    self._broadcast(
                        "download_progress",
                        {
                            "download_id": download.id,
                            "progress": progress,
                            "download_speed": torrent_info.get("dlspeed", 0),
                            "eta": torrent_info.get("eta"),
                        },
                    )

                processed += 1

            db.commit()
            return processed

        except Exception as exc:
            logger.error("Error during download monitoring: %s", exc)
            db.rollback()
            return 0
        finally:
            db.close()

    def handle_completed(
        self,
        download: "Download",
        db: "Session | None" = None,
    ) -> bool:
        """
        Handle a torrent that has finished downloading.

        Locates the EPUB file via qBit, updates the Download record to COMPLETED,
        and transitions the associated Book to IMPORTING.

        Args:
            download:   Download model instance (must belong to an active Session if db is passed).
            db:         Optional existing Session; if None a new one is opened and committed.

        Returns:
            True if handled successfully, False on error.
        """
        owns_session = db is None
        if owns_session:
            db = self._db_factory()
            if download not in db:
                download = db.merge(download)

        try:
            epub_path = self.qbit.get_completed_file_path(download.torrent_hash)

            if not epub_path:
                logger.warning(
                    "No EPUB found for completed torrent %s... (Download id=%d)",
                    download.torrent_hash[:16],
                    download.id,
                )
                transition_download(download, DownloadStatus.FAILED)
                download.error_message = "No EPUB file found in completed torrent"
                self._broadcast(
                    "download_failed",
                    {
                        "book_id": download.book_id,
                        "download_id": download.id,
                        "reason": download.error_message,
                    },
                )
            else:
                transition_download(download, DownloadStatus.COMPLETED)
                download.file_path = str(epub_path)
                download.completed_at = datetime.now(UTC)

                book = db.query(Book).filter(Book.id == download.book_id).first()
                if book:
                    if not self._transition_book(book, BookStatus.IMPORTING, download=download):
                        logger.warning(
                            "Could not transition book %d from %r → importing",
                            download.book_id,
                            book.status,
                        )

                logger.info(
                    "Download handled: %r → %s",
                    download.torrent_name,
                    epub_path,
                )

            if owns_session:
                db.commit()
            return True

        except Exception as exc:
            logger.error("Error handling completed download id=%d: %s", download.id, exc)
            self._broadcast(
                "download_failed",
                {"book_id": download.book_id, "download_id": download.id, "reason": str(exc)},
            )
            if owns_session:
                db.rollback()
            return False
        finally:
            if owns_session:
                db.close()

    def reconcile_on_startup(self) -> dict[str, int]:
        """
        Sync DB download state with qBittorrent state on app startup.

        Handles the case where the app was restarted while downloads were in flight:
        - Torrents missing from qBit   → marked FAILED
        - Already-completed torrents   → calls handle_completed (unless already past COMPLETED)
        - Still-downloading torrents   → status corrected if needed

        Returns:
            Dict with counts: {"reconciled": N, "failed": N, "completed": N}
        """
        db = self._db_factory()
        try:
            terminal_statuses = [DownloadStatus.IMPORTED.value, DownloadStatus.FAILED.value]
            downloads = db.query(Download).filter(~Download.status.in_(terminal_statuses)).all()

            if not downloads:
                logger.debug("No active downloads to reconcile on startup")
                return {"reconciled": 0, "failed": 0, "completed": 0}

            logger.info("Reconciling %d active download(s) with qBittorrent state", len(downloads))

            torrents = self.qbit.get_torrents(category=self.category)
            torrent_map: dict[str, dict] = {t["hash"]: t for t in torrents}

            counts: dict[str, int] = {"reconciled": 0, "failed": 0, "completed": 0}

            for download in downloads:
                torrent_info = torrent_map.get(download.torrent_hash)

                if not torrent_info:
                    repaired_hash = extract_info_hash_from_url(download.download_url)
                    if repaired_hash and repaired_hash != download.torrent_hash and repaired_hash in torrent_map:
                        try:
                            logger.info(
                                "Repairing legacy torrent_hash for Download id=%d: %s... → %s...",
                                download.id,
                                download.torrent_hash[:16],
                                repaired_hash[:16],
                            )
                            download.torrent_hash = repaired_hash
                            if download.error_message == "Torrent not found in qBittorrent after restart":
                                download.error_message = None
                            db.flush()
                            torrent_info = torrent_map[repaired_hash]
                        except IntegrityError:
                            db.rollback()
                            logger.warning(
                                "UNIQUE conflict repairing torrent_hash for Download id=%d — leaving unrepaired",
                                download.id,
                            )

                if not torrent_info:
                    if download.status in (
                        DownloadStatus.COMPLETED.value,
                        DownloadStatus.IMPORTING.value,
                    ):
                        counts["reconciled"] += 1
                        continue

                    if download.created_at:
                        now = datetime.now(UTC)
                        if download.created_at.tzinfo is None:
                            now = now.replace(tzinfo=None)
                        age = (now - download.created_at).total_seconds()
                    else:
                        age = 999_999

                    if age < 60:
                        logger.debug(
                            "Skipping reconcile for Download id=%d (created %.1fs ago — within grace window)",
                            download.id,
                            age,
                        )
                        counts["reconciled"] += 1
                        continue

                    logger.warning(
                        "Torrent %s... missing from qBit on startup (Download id=%d, book_id=%d, url=%r)",
                        download.torrent_hash[:16],
                        download.id,
                        download.book_id,
                        download.download_url,
                    )
                    download.status = DownloadStatus.FAILED.value
                    download.error_message = "Torrent not found in qBittorrent after restart"
                    counts["failed"] += 1
                    continue

                state = torrent_info.get("state", TorrentState.UNKNOWN)
                progress = torrent_info.get("progress", 0.0)
                is_complete = state in DOWNLOAD_COMPLETE_STATES or progress >= 1.0

                if is_complete and download.status not in (
                    DownloadStatus.COMPLETED.value,
                    DownloadStatus.IMPORTING.value,
                ):
                    if download.status == DownloadStatus.QUEUED.value:
                        download.status = DownloadStatus.DOWNLOADING.value
                    self.handle_completed(download, db=db)
                    counts["completed"] += 1

                elif state in (TorrentState.ERROR, TorrentState.MISSING_FILES):
                    download.status = DownloadStatus.FAILED.value
                    download.error_message = f"Torrent in error state ({state}) in qBittorrent"
                    counts["failed"] += 1

                elif state in ACTIVE_DL_STATES and download.status == DownloadStatus.QUEUED.value:
                    download.status = DownloadStatus.DOWNLOADING.value
                    counts["reconciled"] += 1

                else:
                    counts["reconciled"] += 1

            db.commit()
            logger.info(
                "Startup reconciliation complete: %d active, %d failed, %d completed",
                counts["reconciled"],
                counts["failed"],
                counts["completed"],
            )
            return counts

        except Exception as exc:
            logger.error("Error during startup reconciliation: %s", exc)
            db.rollback()
            return {"reconciled": 0, "failed": 0, "completed": 0}
        finally:
            db.close()

    def add_torrent(self, download: "Download") -> bool:
        """Add an existing QUEUED download's torrent to qBittorrent.

        Called by the pipeline when a book transitions from GRABBED to DOWNLOADING.
        Uses the download_url field which stores the magnet link or HTTP torrent URL.

        Args:
            download: A Download model instance with download_url and category set.

        Returns:
            True if the torrent was added successfully, False otherwise.
        """
        if not download.download_url:
            logger.error("Download %d has no URL — cannot add to qBittorrent", download.id)
            return False
        return self.qbit.add_torrent(torrent_url=download.download_url, category=self.category)

    def get_completed_file_path(self, download: "Download") -> str | None:
        """Check if a torrent download is complete and return the EPUB file path.

        Delegates to QBittorrentClient.get_completed_file_path using the
        download's torrent_hash. Returns the path as a string, or None if the
        download is not yet complete or the torrent is not found.

        Args:
            download: A Download model instance with torrent_hash set.

        Returns:
            Absolute path string to the downloaded EPUB, or None if not complete.
        """
        if not download.torrent_hash:
            logger.warning("Download %d has no torrent_hash — cannot check completion", download.id)
            return None
        result = self.qbit.get_completed_file_path(download.torrent_hash)
        return str(result) if result is not None else None

    def _configure_file_priorities(self, torrent_hash: str) -> "str | None":
        """
        For multi-file torrents, set priority 0 on all non-EPUB files.

        Args:
            torrent_hash: qBittorrent info hash.

        Returns:
            The filename of the first EPUB found, or None for single-file / no EPUB.
        """
        files = self.qbit.get_torrent_files(torrent_hash)
        if not files or len(files) <= 1:
            return None

        non_epub_ids: list[int] = []
        epub_name: str | None = None

        for idx, file_info in enumerate(files):
            name = file_info.get("name", "")
            if name.lower().endswith(".epub"):
                if epub_name is None:
                    epub_name = name
                    logger.debug("Found EPUB in multi-file torrent %s: %s", torrent_hash[:16], name)
            else:
                non_epub_ids.append(idx)

        if non_epub_ids:
            logger.info(
                "Setting priority 0 on %d non-EPUB file(s) in torrent %s...",
                len(non_epub_ids),
                torrent_hash[:16],
            )
            self.qbit.set_file_priority(torrent_hash, non_epub_ids, priority=0)

        return epub_name

    def _update_progress_tracking(self, download: "Download", torrent_info: dict) -> None:
        if download.last_progress_at is None:
            download.last_progress_at = download.created_at or datetime.utcnow()

        downloaded = torrent_info.get("downloaded", 0) or 0
        if downloaded > (download.bytes_at_last_check or 0):
            download.bytes_at_last_check = downloaded
            download.last_progress_at = datetime.utcnow()

    def _check_stall_and_timeout(self, download: "Download", db: "Session") -> bool:
        if download.status not in {DownloadStatus.DOWNLOADING.value, DownloadStatus.QUEUED.value}:
            return False

        now = datetime.utcnow()
        created_at = download.created_at
        if created_at is not None and created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        last_progress = download.last_progress_at
        if last_progress is not None and last_progress.tzinfo is not None:
            last_progress = last_progress.replace(tzinfo=None)

        # Hard ceiling fires regardless of recent progress and is checked first
        # so a 24h+ download that just made progress still gets killed.
        if created_at is not None and (now - created_at) > timedelta(hours=DOWNLOAD_TOTAL_TIMEOUT_HOURS):
            self._fail_for_stall(
                download,
                db,
                reason=FailureReason.DOWNLOAD_TIMEOUT,
                message=f"Total download time exceeded {DOWNLOAD_TOTAL_TIMEOUT_HOURS} hours",
            )
            return True

        if last_progress is not None and (now - last_progress) > timedelta(minutes=DOWNLOAD_STALL_THRESHOLD_MIN):
            self._fail_for_stall(
                download,
                db,
                reason=FailureReason.DOWNLOAD_STALLED,
                message=f"Stalled: no progress for {DOWNLOAD_STALL_THRESHOLD_MIN} minutes",
            )
            return True

        return False

    def _fail_for_stall(
        self,
        download: "Download",
        db: "Session",
        *,
        reason: FailureReason,
        message: str,
    ) -> None:
        if transition_download(download, DownloadStatus.FAILED):
            download.error_message = message
            logger.warning(
                "Download %s: %r (id=%d, hash=%s...)",
                reason.value,
                download.torrent_name,
                download.id,
                download.torrent_hash[:16],
            )

        book = db.query(Book).filter(Book.id == download.book_id).first()
        if book is not None:
            book.failure_reason = reason.value
            old_status = book.status
            if transition_book(book, BookStatus.FAILED):
                self._broadcast(
                    "book_status_changed",
                    {
                        "book_id": book.id,
                        "old_status": old_status,
                        "new_status": book.status,
                        "title": book.title,
                    },
                )
                self._broadcast(
                    "book_failed",
                    {"book_id": book.id, "title": book.title, "reason": message},
                )
            else:
                logger.warning(
                    "Could not transition book %d from %r → FAILED for stall",
                    book.id,
                    old_status,
                )

        try:
            self.qbit.delete_torrent(download.torrent_hash)
        except Exception as exc:
            logger.warning(
                "Failed to delete stalled torrent %s... from qBit: %s",
                download.torrent_hash[:16],
                exc,
            )

        self._broadcast(
            "download_failed",
            {"book_id": download.book_id, "download_id": download.id, "reason": message},
        )

    def _broadcast(self, event: str, data: dict) -> None:
        if self.ws_manager:
            self.ws_manager.broadcast_sync(event, data)

    def _transition_book(self, book: Book, target_status: str, download: Download | None = None) -> bool:
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

        if target_status == BookStatus.GRABBED:
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

        return True
