"""
Sync Service - Core sync logic with event emission for web UI.

This service handles the main sync workflow:
1. Fetch books from Hardcover
2. Match books in Readarr
3. Transfer files to Kindle
4. Track progress and emit events
"""

import asyncio
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.clients.hardcover_client import HardcoverClient
from backend.clients.kindle_client import KindleClient
from backend.clients.readarr_client import ReadarrClient
from backend.config import get_kindle_by_id, get_sync_status_ids, load_config
from backend.database import SessionLocal
from backend.models.sync_run import BookResult, SyncRun

logger = logging.getLogger(__name__)

# Map Hardcover status_id to readable strings
READING_STATUS_MAP = {
    1: "want_to_read",
    2: "currently_reading",
    3: "read",
}


class SyncService:
    """
    Sync service that processes books and emits events for the web UI.
    """

    def __init__(
        self,
        event_callback: Callable[[str, Any], None] | None = None,
    ):
        """
        Initialize the sync service.

        Args:
            event_callback: Async function to call with (event_name, data) for each event
        """

        async def _noop_callback(*args):
            pass

        self.emit = event_callback or _noop_callback
        self._cancelled = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _emit_sync(self, event: str, data: Any) -> None:
        """
        Emit an event synchronously (for use in paramiko callbacks).

        This bridges the sync paramiko callback to our async emit function
        by scheduling the coroutine on the event loop from another thread.
        """
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.emit(event, data), self._loop)
            # Don't wait for result to avoid blocking the transfer
        except Exception:
            pass  # Ignore emission errors during transfer

    def cancel(self):
        """Request cancellation of the current sync."""
        self._cancelled = True

    async def _add_book_to_readarr(
        self,
        readarr: ReadarrClient,
        book_metadata: dict,
        title: str,
        auto_add_config: dict,
        dry_run: bool = False,
    ) -> bool:
        """
        Add a book to Readarr if auto-add is enabled.

        Args:
            readarr: ReadarrClient instance
            book_metadata: Book metadata from Readarr lookup
            title: Book title (for logging)
            auto_add_config: Auto-add configuration from config
            dry_run: If True, only log what would be added

        Returns:
            True if book was added successfully (or would be in dry-run), False otherwise
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would add book to Readarr: {title}")
            return True

        try:
            # Get Readarr configuration
            root_folders = readarr.get_root_folders()
            quality_profiles = readarr.get_quality_profiles()
            metadata_profiles = readarr.get_metadata_profiles()

            if not root_folders:
                logger.error("No root folders found in Readarr, cannot add book")
                return False

            if not quality_profiles:
                logger.error("No quality profiles found in Readarr, cannot add book")
                return False

            if not metadata_profiles:
                logger.error("No metadata profiles found in Readarr, cannot add book")
                return False

            # Use first root folder and default profiles
            root_folder_path = root_folders[0].get("path")

            # Find default quality profile (or use first one)
            default_quality = next((p for p in quality_profiles if p.get("default", False)), quality_profiles[0])
            quality_profile_id = default_quality.get("id")

            # Find default metadata profile (or use first one)
            default_metadata = next((p for p in metadata_profiles if p.get("default", False)), metadata_profiles[0])
            metadata_profile_id = default_metadata.get("id")

            # Determine if we should search immediately
            search_immediately = auto_add_config.get("search_immediately", True)

            logger.info(f"Adding book to Readarr: {title}")
            logger.debug(f"  Root folder: {root_folder_path}")
            logger.debug(f"  Quality profile: {default_quality.get('name')}")
            logger.debug(f"  Metadata profile: {default_metadata.get('name')}")
            logger.debug(f"  Search immediately: {search_immediately}")

            # Transform flat author fields into nested structure expected by add_book_to_library()
            if "author" not in book_metadata:
                # Extract author name from authorTitle field
                author_title_raw = book_metadata.get("authorTitle", "")
                book_title = book_metadata.get("title", "")

                # Try to extract author name by removing book title from authorTitle
                author_name = author_title_raw
                if book_title and author_title_raw.endswith(book_title):
                    author_name = author_title_raw[: -len(book_title)].strip()

                logger.info(f"  Extracted author name: '{author_name}'")

                # Look up the author to get full metadata including foreignAuthorId
                author_metadata = readarr.lookup_author(author_name)

                if author_metadata:
                    logger.info(
                        f"  Found author metadata with foreignAuthorId: {author_metadata.get('foreignAuthorId')}"
                    )
                    book_metadata["author"] = author_metadata
                else:
                    logger.warning(f"  Could not find author metadata for: {author_name}")
                    book_metadata["author"] = {"authorName": author_name}

            # Add the book
            result = readarr.add_book_to_library(
                book_metadata=book_metadata,
                quality_profile_id=quality_profile_id,
                metadata_profile_id=metadata_profile_id,
                root_folder_path=root_folder_path,
                search=search_immediately,
            )

            if result:
                logger.info(f"Successfully added to Readarr: {title}")
                return True
            else:
                logger.error(f"Failed to add to Readarr: {title}")
                return False

        except Exception as e:
            logger.error(f"Error adding book to Readarr '{title}': {e}")
            return False

    def _apply_path_mapping(self, readarr_path: str, path_mappings: list) -> str:
        """Apply path mapping to convert Readarr's internal path to host path."""
        if not path_mappings:
            return readarr_path

        for mapping in path_mappings:
            readarr_prefix = mapping.get("readarr_path", "")
            local_prefix = mapping.get("local_path", "")

            if readarr_path.startswith(readarr_prefix):
                mapped_path = readarr_path.replace(readarr_prefix, local_prefix, 1)
                logger.debug(f"Path mapping: {readarr_path} -> {mapped_path}")
                return mapped_path

        return readarr_path

    async def run_sync(
        self,
        kindle_device: str | None = None,
        dry_run: bool = False,
        trigger_type: str = "manual",
    ) -> dict:
        """
        Run a sync operation.

        Args:
            kindle_device: Target Kindle device ID (uses first if not specified)
            dry_run: If True, simulate without transferring
            trigger_type: How the sync was triggered (manual/scheduled)

        Returns:
            Dictionary with sync results and statistics
        """
        self._cancelled = False
        self._loop = asyncio.get_running_loop()
        config = load_config()

        # Get status IDs from global config (in priority order)
        status_ids = get_sync_status_ids()

        # Create database session and sync run record
        db = SessionLocal()
        sync_run = SyncRun(
            started_at=datetime.utcnow(),
            status="running",
            trigger_type=trigger_type,
            kindle_device=kindle_device,
            status_ids=status_ids,
            dry_run=dry_run,
        )
        db.add(sync_run)
        db.commit()
        db.refresh(sync_run)

        # Emit sync_started immediately so UI shows progress right away
        await self.emit(
            "sync_started",
            {
                "sync_run_id": sync_run.id,
                "status_ids": status_ids,
                "dry_run": dry_run,
            },
        )

        try:
            # Initialize clients
            hardcover_config = config.get("hardcover", {})
            readarr_config = config.get("readarr", {})
            matching_config = config.get("matching", {})
            transfer_config = config.get("transfer", {})

            # Apply dry_run from config if not explicitly set
            if not dry_run:
                dry_run = transfer_config.get("dry_run", False)

            skip_existing = transfer_config.get("skip_existing", True)
            folder_organization = transfer_config.get("folder_organization", "flat")
            cleanup_enabled = transfer_config.get("cleanup_enabled", False)
            cleanup_sdr_folders = transfer_config.get("cleanup_sdr_folders", True)
            cleanup_protected_paths = transfer_config.get("cleanup_protected_paths", [])
            path_mappings = readarr_config.get("path_mappings", [])
            auto_add_config = readarr_config.get("auto_add", {})
            auto_add_enabled = auto_add_config.get("enabled", False)

            hardcover = HardcoverClient(
                api_token=hardcover_config.get("api_token", ""),
                api_url=hardcover_config.get("api_url", "https://api.hardcover.app/v1/graphql"),
            )

            readarr = ReadarrClient(
                api_key=readarr_config.get("api_key", ""),
                base_url=readarr_config.get("base_url", "http://localhost:8787"),
            )

            # Get Kindle client
            kindle_client = None
            if kindle_device:
                kindle_config = get_kindle_by_id(kindle_device)
            else:
                # Use first Kindle
                kindles = config.get("kindles", [])
                kindle_config = kindles[0] if kindles else None

            if kindle_config:
                kindle_client = KindleClient.from_config(kindle_config)
                sync_run.kindle_device = kindle_config.get("id")

            # Fetch books from Hardcover
            logger.info(f"Fetching books from Hardcover with status IDs: {status_ids}")
            books = hardcover.get_books_by_status(status_ids)

            # Sort books by status priority: Currently Reading (2) > Want to Read (1) > Read (3)
            STATUS_PRIORITY = {2: 0, 1: 1, 3: 2}
            books.sort(key=lambda b: STATUS_PRIORITY.get(b.get("status_id", 1), 99))

            sync_run.total_books = len(books)
            db.commit()

            await self.emit(
                "books_fetched",
                {
                    "sync_run_id": sync_run.id,
                    "total_books": len(books),
                },
            )

            # Process each book
            stats = {
                "matched": 0,
                "transferred": 0,
                "failed": 0,
                "not_found": 0,
                "skipped": 0,
                "added_to_readarr": 0,
                "cleaned_up": 0,
            }

            # Track files that should be on the Kindle (for cleanup)
            expected_files_on_kindle = []

            for i, book in enumerate(books):
                if self._cancelled:
                    sync_run.status = "cancelled"
                    break

                title = book.get("title", "Unknown")
                author = book.get("author_string", "")
                isbns = book.get("isbns", [])
                cover_url = book.get("cover_url")
                series_name = book.get("series_name")

                # Emit progress
                await self.emit(
                    "book_progress",
                    {
                        "sync_run_id": sync_run.id,
                        "current": i + 1,
                        "total": len(books),
                        "book": {"title": title, "author": author, "cover_url": cover_url, "status": "processing"},
                    },
                )

                # Create book result record
                status_id = book.get("status_id")
                reading_status = READING_STATUS_MAP.get(status_id) if status_id else None

                book_result = BookResult(
                    sync_run_id=sync_run.id,
                    hardcover_id=str(book.get("hardcover_id", "")),
                    title=title,
                    author=author,
                    isbns=isbns,
                    cover_url=cover_url,
                    reading_status=reading_status,
                    status="processing",
                    processed_at=datetime.utcnow(),
                )
                db.add(book_result)
                db.commit()

                # Search in Readarr
                fuzzy_threshold = matching_config.get("fuzzy_threshold", 80)
                result = readarr.find_book_and_files(
                    title=title,
                    author=author,
                    isbns=isbns,
                    format_filter="epub",
                    fuzzy_threshold=fuzzy_threshold,
                    return_metadata_only=True,
                )

                if not result:
                    book_result.status = "not_found"
                    stats["not_found"] += 1
                    db.commit()

                    await self.emit(
                        "book_completed",
                        {
                            "sync_run_id": sync_run.id,
                            "book": {"title": title, "cover_url": cover_url, "status": "not_found"},
                        },
                    )
                    continue

                book_data = result.get("book", {})
                files = result.get("files", [])
                has_files = result.get("has_files", False)

                book_result.readarr_book_id = book_data.get("id")

                if not has_files:
                    # Book found but no files
                    stats["matched"] += 1

                    if auto_add_enabled:
                        # Try to add book to Readarr
                        logger.info(f"Book exists in Readarr metadata but has no files: {title}")
                        await self.emit(
                            "book_progress",
                            {
                                "sync_run_id": sync_run.id,
                                "current": i + 1,
                                "total": len(books),
                                "book": {
                                    "title": title,
                                    "author": author,
                                    "cover_url": cover_url,
                                    "status": "adding_to_readarr",
                                },
                            },
                        )

                        if await self._add_book_to_readarr(readarr, book_data, title, auto_add_config, dry_run):
                            stats["added_to_readarr"] += 1
                            book_result.status = "added_to_readarr"
                        else:
                            book_result.status = "add_failed"
                            book_result.error_message = "Failed to add to Readarr"
                    else:
                        book_result.status = "matched_no_files"

                    db.commit()

                    await self.emit(
                        "book_completed",
                        {
                            "sync_run_id": sync_run.id,
                            "book": {"title": title, "cover_url": cover_url, "status": book_result.status},
                        },
                    )
                    continue

                # Transfer each file
                stats["matched"] += 1

                for file_data in files:
                    file_path = file_data.get("path", "")
                    local_path = self._apply_path_mapping(file_path, path_mappings)

                    if dry_run:
                        book_result.status = "dry_run"
                        book_result.file_path = local_path
                        continue

                    if not kindle_client:
                        book_result.status = "no_kindle"
                        book_result.error_message = "No Kindle configured"
                        break

                    # Create progress callback for transfer monitoring
                    file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
                    transfer_start = time.time()
                    last_emit_time = [0.0]  # Use list for nonlocal mutation

                    def make_progress_callback(
                        sync_run_id: int,
                        book_title: str,
                        total_size: int,
                        last_emit_time: list[float],
                        transfer_start: float,
                    ):
                        def progress_callback(bytes_so_far: int, bytes_total: int):
                            now = time.time()
                            # Throttle to max 4 emissions per second
                            if now - last_emit_time[0] < 0.25 and bytes_so_far < bytes_total:
                                return
                            last_emit_time[0] = now

                            elapsed = now - transfer_start
                            speed = bytes_so_far / elapsed if elapsed > 0 else 0
                            remaining = (bytes_total - bytes_so_far) / speed if speed > 0 else 0
                            percentage = (bytes_so_far / bytes_total * 100) if bytes_total > 0 else 0

                            self._emit_sync(
                                "transfer_progress",
                                {
                                    "sync_run_id": sync_run_id,
                                    "book_title": book_title,
                                    "bytes_transferred": bytes_so_far,
                                    "bytes_total": bytes_total,
                                    "percentage": round(percentage, 1),
                                    "speed_bytes_per_sec": round(speed),
                                    "eta_seconds": round(remaining),
                                },
                            )

                        return progress_callback

                    progress_cb = make_progress_callback(sync_run.id, title, file_size, last_emit_time, transfer_start)

                    # Transfer to Kindle
                    transfer_result = kindle_client.transfer_file(
                        local_path=local_path,
                        skip_existing=skip_existing,
                        author=author,
                        series=series_name or "",
                        folder_organization=folder_organization,
                        progress_callback=progress_cb,
                    )

                    if transfer_result["success"]:
                        # Track this file as expected on Kindle (for cleanup)
                        filename = os.path.basename(local_path)
                        expected_files_on_kindle.append(filename)

                        if transfer_result["status"] == "skipped":
                            book_result.status = "skipped"
                            stats["skipped"] += 1
                        else:
                            book_result.status = "transferred"
                            book_result.file_path = local_path
                            book_result.file_size = transfer_result.get("file_size", 0)
                            stats["transferred"] += 1
                    else:
                        book_result.status = "failed"
                        book_result.error_message = transfer_result.get("error", "Transfer failed")
                        stats["failed"] += 1

                    break  # Only transfer first matching file

                db.commit()

                await self.emit(
                    "book_completed",
                    {
                        "sync_run_id": sync_run.id,
                        "book": {
                            "title": title,
                            "cover_url": cover_url,
                            "status": book_result.status,
                            "file_size": book_result.file_size,
                            "error_message": book_result.error_message,
                        },
                    },
                )

                # Small delay to prevent overwhelming
                await asyncio.sleep(0.1)

            # Cleanup phase: Remove books not in sync list
            if cleanup_enabled and kindle_client and not dry_run and not self._cancelled:
                logger.info("Starting cleanup phase...")
                await self.emit(
                    "cleanup_started",
                    {
                        "sync_run_id": sync_run.id,
                    },
                )

                try:
                    # First, find orphaned books to track them individually
                    orphans = kindle_client.find_orphaned_books(
                        expected_filenames=expected_files_on_kindle,
                        protected_paths=cleanup_protected_paths,
                    )

                    # Create BookResult records for each removed book before deletion
                    for orphan_path in orphans:
                        filename = os.path.basename(orphan_path)
                        # Extract title from filename (remove extension)
                        title = os.path.splitext(filename)[0]

                        removed_result = BookResult(
                            sync_run_id=sync_run.id,
                            title=title,
                            status="removed",
                            file_path=orphan_path,
                            processed_at=datetime.utcnow(),
                        )
                        db.add(removed_result)
                    db.commit()

                    # Now perform the actual cleanup
                    cleanup_result = kindle_client.cleanup_orphaned_books(
                        expected_filenames=expected_files_on_kindle,
                        protected_paths=cleanup_protected_paths,
                        delete_sdr=cleanup_sdr_folders,
                    )
                    stats["cleaned_up"] = cleanup_result.get("deleted", 0)
                    logger.info(
                        f"Cleanup complete: {cleanup_result['deleted']} deleted, {cleanup_result['failed']} failed"
                    )

                    await self.emit(
                        "cleanup_completed",
                        {
                            "sync_run_id": sync_run.id,
                            "cleaned_up": cleanup_result["deleted"],
                            "cleanup_failed": cleanup_result["failed"],
                        },
                    )
                except Exception as e:
                    logger.error(f"Cleanup phase failed: {e}")
                    await self.emit(
                        "cleanup_failed",
                        {
                            "sync_run_id": sync_run.id,
                            "error": str(e),
                        },
                    )

            # Update sync run with final stats
            sync_run.matched = stats["matched"]
            sync_run.transferred = stats["transferred"]
            sync_run.failed = stats["failed"]
            sync_run.not_found = stats["not_found"]
            sync_run.skipped = stats["skipped"]
            sync_run.added_to_readarr = stats.get("added_to_readarr", 0)
            sync_run.cleaned_up = stats.get("cleaned_up", 0)
            sync_run.completed_at = datetime.utcnow()
            sync_run.status = "completed" if not self._cancelled else "cancelled"
            db.commit()

            await self.emit(
                "sync_completed",
                {
                    "sync_run_id": sync_run.id,
                    "stats": {
                        "total_books": sync_run.total_books,
                        "matched": sync_run.matched,
                        "transferred": sync_run.transferred,
                        "failed": sync_run.failed,
                        "not_found": sync_run.not_found,
                        "skipped": sync_run.skipped,
                        "cleaned_up": sync_run.cleaned_up,
                    },
                },
            )

            return sync_run.to_dict()

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            sync_run.status = "failed"
            sync_run.error_message = str(e)
            sync_run.completed_at = datetime.utcnow()
            db.commit()

            await self.emit(
                "sync_failed",
                {
                    "sync_run_id": sync_run.id,
                    "error": str(e),
                },
            )

            raise

        finally:
            db.close()


# Global sync state
_current_sync: SyncService | None = None
_sync_lock = asyncio.Lock()


async def start_sync(
    kindle_device: str | None = None,
    dry_run: bool = False,
    trigger_type: str = "manual",
    event_callback: Callable | None = None,
) -> dict:
    """
    Start a sync operation.

    Status IDs are now read from global config settings.

    Returns:
        Sync run result dictionary
    """
    global _current_sync

    async with _sync_lock:
        if _current_sync is not None:
            raise RuntimeError("A sync is already in progress")

        _current_sync = SyncService(event_callback=event_callback)

    try:
        result = await _current_sync.run_sync(
            kindle_device=kindle_device,
            dry_run=dry_run,
            trigger_type=trigger_type,
        )
        return result
    finally:
        async with _sync_lock:
            _current_sync = None


async def stop_sync() -> bool:
    """Cancel the current sync operation."""
    global _current_sync

    async with _sync_lock:
        if _current_sync is not None:
            _current_sync.cancel()
            return True
        return False


def is_sync_running() -> bool:
    """Check if a sync is currently running."""
    return _current_sync is not None


async def run_scheduled_sync(
    kindle_device: str | None = None,
    dry_run: bool = False,
    **kwargs,
):
    """Entry point for scheduled syncs."""
    try:
        await start_sync(
            kindle_device=kindle_device,
            dry_run=dry_run,
            trigger_type="scheduled",
        )
    except RuntimeError:
        logger.warning("Scheduled sync skipped - another sync is running")
    except Exception as e:
        logger.error(f"Scheduled sync failed: {e}")
