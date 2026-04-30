# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false
"""Import service for copying EPUBs to library and writing metadata."""

import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from backend.constants import MAX_COLLISION_ATTEMPTS, MAX_FILENAME_LENGTH
from backend.errors import FailureReason, PipelineError
from backend.models.book import Book, BookStatus, FolderOrganization, RootFolder
from backend.services.epub_service import EpubMetadata, EpubService
from backend.services.pipeline_states import transition_book
from backend.services.websocket_manager import WebSocketManager
from backend.utils.atomic import atomic_copy
from backend.utils.events import log_event

logger = logging.getLogger(__name__)

_UNSAFE_CHARS_RE = re.compile(r'[/\\:*?"<>|]')
_HASH_SUFFIX_LEN = 8


def sanitize_path_component(name: str) -> str:
    sanitized = _UNSAFE_CHARS_RE.sub("_", name)
    sanitized = sanitized.strip(". ")
    sanitized = sanitized or "_"

    if len(sanitized) > MAX_FILENAME_LENGTH:
        hash_suffix = hashlib.md5(sanitized.encode()).hexdigest()[:_HASH_SUFFIX_LEN]
        truncate_to = MAX_FILENAME_LENGTH - _HASH_SUFFIX_LEN - 1
        sanitized = sanitized[:truncate_to] + "_" + hash_suffix

    return sanitized


class BookImportError(Exception):
    pass


class ImportDuplicateError(BookImportError):
    pass


class ImportInvalidEpubError(BookImportError):
    pass


class ImportStateError(BookImportError):
    pass


class ImportService:
    """Imports EPUB files into the library: copy, metadata write, DB update."""

    def __init__(
        self,
        db: Session,
        epub_service: EpubService | None = None,
        ws_manager: WebSocketManager | None = None,
    ) -> None:
        self.db = db
        self.epub_service = epub_service or EpubService()
        self.ws_manager = ws_manager

    def import_book(self, book_id: int, epub_path: str | Path) -> Book:
        """Import an EPUB into the library for the given book.

        Validates the EPUB, transitions Book → IMPORTING, copies to the library,
        writes metadata, updates file_path/file_size, then transitions → IN_LIBRARY.
        On any failure, transitions to FAILED.

        Raises:
            ImportStateError: Book not found, no root folder, or invalid state.
            ImportInvalidEpubError: Source is not a valid EPUB.
            ImportDuplicateError: Destination file already exists.
            BookImportError: Copy or metadata-write failure.
        """
        epub_path = Path(epub_path)

        book = self.db.get(Book, book_id)
        if book is None:
            raise ImportStateError(f"Book {book_id} not found")

        if book.root_folder_id is None:
            raise ImportStateError(f"Book {book_id} has no root folder assigned")

        root_folder = self.db.get(RootFolder, book.root_folder_id)
        if root_folder is None:
            raise ImportStateError(f"Root folder {book.root_folder_id} not found")

        if not self.epub_service.validate_epub(epub_path):
            raise ImportInvalidEpubError(f"Source file is not a valid EPUB: {epub_path}")

        if book.status != BookStatus.IMPORTING.value:
            if not self._transition_book(book, BookStatus.IMPORTING.value):
                raise ImportStateError(f"Cannot transition book {book_id} from {book.status!r} to IMPORTING")
            self.db.flush()

        self._broadcast("import_started", {"book_id": book.id, "title": book.title})

        try:
            dest_path = self.organize_path(book, root_folder)
            dest_path = self._resolve_collision(dest_path)

            self.copy_to_library(epub_path, dest_path)

            is_confident, reason = self.epub_service.verify_content(dest_path, book)
            if not is_confident:
                logger.warning("Low confidence EPUB for book %s: %s", book.id, reason)
                book.low_confidence = True
                book.failure_reason = FailureReason.CONTENT_MISMATCH_LOW_CONFIDENCE.value

            if self.epub_service.is_drm_protected(dest_path):
                logger.warning("DRM detected for book %s; skipping metadata write", book.id)
                book.low_confidence = True
                book.failure_reason = FailureReason.IMPORT_DRM_PROTECTED.value
            else:
                self.write_metadata(book, dest_path)

            relative_path = dest_path.relative_to(root_folder.path)
            book.file_path = str(relative_path)
            book.file_size = dest_path.stat().st_size

            if not self._transition_book(book, BookStatus.IN_LIBRARY.value):
                raise BookImportError(f"Failed to transition book {book_id} to IN_LIBRARY")

            self.db.flush()
            self._broadcast(
                "import_completed",
                {"book_id": book.id, "title": book.title, "file_path": str(dest_path)},
            )
            logger.info("Successfully imported book %d to %s", book_id, dest_path)
            log_event(
                "book_imported",
                book_id=book.id,
                file_path=str(dest_path),
                size_bytes=book.file_size or 0,
                low_confidence=bool(book.low_confidence),
            )
            return book

        except Exception as exc:
            self._broadcast(
                "import_failed",
                {"book_id": book.id, "title": book.title, "reason": str(exc)},
            )
            if book.status == BookStatus.IMPORTING.value:
                self._transition_book(book, BookStatus.FAILED.value)
                self.db.flush()
            raise

    def _resolve_collision(self, dest: Path) -> Path:
        """If dest exists, return a versioned path: 'name (1).epub', '(2)', etc.

        Raises:
            PipelineError(IMPORT_FILE_COLLISION): More than MAX_COLLISION_ATTEMPTS exist.
        """
        if not dest.exists():
            return dest

        for i in range(1, MAX_COLLISION_ATTEMPTS + 1):
            versioned = dest.with_stem(f"{dest.stem} ({i})")
            if not versioned.exists():
                logger.info("Collision: using versioned name %s", versioned.name)
                return versioned

        raise PipelineError(
            f"Too many collisions for {dest.name} (>{MAX_COLLISION_ATTEMPTS})",
            FailureReason.IMPORT_FILE_COLLISION,
        )

    def organize_path(self, book: Book, root_folder: RootFolder) -> Path:
        """Return the absolute destination path for a book's EPUB.

        Patterns (based on root_folder.folder_organization):
          flat          → {root}/{title}.epub
          author        → {root}/{author}/{title}.epub
          series        → {root}/{series}/{title}.epub  (flat if no series)
          author_series → {root}/{author}/{series}/{title}.epub  (author if no series)
        """
        root = Path(root_folder.path)
        org = root_folder.folder_organization

        author_name = book.author.name if book.author else "Unknown Author"
        safe_author = sanitize_path_component(author_name)
        safe_title = sanitize_path_component(book.title)
        filename = f"{safe_title}.epub"

        if org == FolderOrganization.AUTHOR.value:
            return root / safe_author / filename

        if org == FolderOrganization.SERIES.value:
            if book.series_name:
                return root / sanitize_path_component(book.series_name) / filename
            return root / filename

        if org == FolderOrganization.AUTHOR_SERIES.value:
            if book.series_name:
                return root / safe_author / sanitize_path_component(book.series_name) / filename
            return root / safe_author / filename

        return root / filename

    def copy_to_library(self, source: Path, dest: Path) -> Path:
        """Atomically copy EPUB from source to dest, creating parent dirs.

        Uses atomic_copy: writes to temp file, fsyncs, then renames.
        Destination is either fully written or absent — never partial.

        Raises:
            BookImportError: Source missing.
            PipelineError(IMPORT_DISK_FULL): No space left on device.
            PipelineError(IMPORT_COPY_FAILED): Other OS-level copy failure.
        """
        source = Path(source)
        dest = Path(dest)

        if not source.exists():
            raise BookImportError(f"Source file not found: {source}")

        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            atomic_copy(source, dest)
        except PipelineError:
            raise
        except OSError as exc:
            raise PipelineError(f"Failed to copy {source} to {dest}: {exc}", FailureReason.IMPORT_COPY_FAILED) from exc

        return dest

    def write_metadata(self, book: Book, epub_path: Path) -> None:
        """Write Book metadata (title, authors, series, description) into the EPUB.

        Raises:
            BookImportError: Wraps any EpubService error.
        """
        author_name = book.author.name if book.author else None

        metadata = EpubMetadata(
            title=book.title,
            authors=[author_name] if author_name else [],
            series=book.series_name,
            series_position=book.series_position,
            description=book.description,
        )

        try:
            self.epub_service.write_metadata(epub_path, metadata)
        except Exception as e:
            raise BookImportError(f"Failed to write metadata to {epub_path}: {e}") from e

    def import_epub(self, book: Book, file_path: str) -> bool:
        """Adapter called by the pipeline orchestrator.

        Wraps import_book() with a bool return value for pipeline compatibility.
        Returns True on successful import, False if an exception is raised.

        Args:
            book: The Book model instance to import for.
            file_path: Absolute path string to the EPUB file to import.

        Returns:
            True if import succeeded, False if any error occurred.
        """
        try:
            self.import_book(book.id, file_path)
            return True
        except Exception as exc:
            logger.error("import_epub failed for book %d ('%s'): %s", book.id, book.title, exc)
            return False

    def _broadcast(self, event: str, data: dict) -> None:
        if self.ws_manager:
            self.ws_manager.broadcast_sync(event, data)

    def _transition_book(self, book: Book, target_status: str) -> bool:
        old_status = book.status
        if not transition_book(book, target_status, self.db):
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
        return True
