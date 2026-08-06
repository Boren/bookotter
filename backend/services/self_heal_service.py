"""Pipeline self-heal: template renames + EPUB metadata backfill.

Scanner-linked books enter the library in place — original filename, no
embedded metadata. This service brings every IN_LIBRARY book up to the same
standard as the download→import path: filename from the naming template,
DB metadata embedded in the EPUB.

The caller must hold the pipeline lock. Renames delegate wholesale to
RenameService.apply_locked(); the metadata pass settles each book's
epub_meta_state from NULL ("unknown") into synced / drm / failed. Books are
verified before being rewritten — an EPUB whose embedded metadata already
matches the DB is marked synced without touching the file or re-queuing
Kindle delivery, so the first pass over an existing library doesn't trigger
a mass re-delivery.

Bulk Kindle sync (hardcover_sync_service.run_kindle_sync) does not hold the
pipeline lock, so a rename here can race an in-flight transfer; the sync
tolerates missing files and orphaned device copies are removed by its next
cleanup pass.
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from backend.config import get_first_real_kindle, get_kindle_sync_shelves, load_config
from backend.constants import SELF_HEAL_META_BATCH_SIZE, SELF_HEAL_META_MAX_ATTEMPTS
from backend.models.book import Book, BookStatus, EpubMetaState
from backend.services.epub_service import EpubMetadata, EpubService
from backend.services.import_service import ImportService
from backend.services.rename_service import RenameService
from backend.utils.clock import naive_utcnow
from backend.utils.events import log_event
from backend.utils.kindle_delivery import rearm_kindle_delivery

logger = logging.getLogger(__name__)


class SelfHealService:
    """Rename + metadata self-heal for IN_LIBRARY books; caller holds the pipeline lock."""

    def __init__(
        self,
        db: Session,
        import_service: ImportService | None = None,
        epub_service: EpubService | None = None,
    ) -> None:
        self.db = db
        self.import_service = import_service or ImportService(db, epub_service=epub_service)
        self.epub_service = epub_service or self.import_service.epub_service

    def run(self) -> dict:
        config = load_config()
        real_kindle = get_first_real_kindle(config)
        kindle_shelves = get_kindle_sync_shelves(config)

        rename_result = RenameService(self.db, self.import_service).apply_locked()
        meta = self._sync_metadata_batch(real_kindle, kindle_shelves)

        result = {"renamed": rename_result["renamed"], **meta}
        log_event("self_heal_completed", **result)
        return result

    def _needs_meta_query(self):
        return self.db.query(Book).filter(
            Book.status == BookStatus.IN_LIBRARY.value,
            Book.file_path.isnot(None),
            Book.root_folder_id.isnot(None),
            Book.epub_meta_state.is_(None),
        )

    def _sync_metadata_batch(self, real_kindle: dict | None, kindle_shelves: set[str]) -> dict:
        books = (
            self._needs_meta_query()
            .options(joinedload(Book.author), joinedload(Book.root_folder))
            .order_by(Book.id)
            .limit(SELF_HEAL_META_BATCH_SIZE)
            .all()
        )

        counts = {"meta_verified": 0, "meta_rewritten": 0, "meta_drm": 0, "meta_failed": 0}
        for book in books:
            book_id = book.id
            try:
                outcome = self._heal_one(book, real_kindle, kindle_shelves)
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                refetched = self.db.get(Book, book_id)
                if refetched is not None:
                    self._record_failure(refetched, str(exc))
                    self.db.commit()
                outcome = "meta_failed"
            counts[outcome] += 1

        counts["meta_remaining"] = self._needs_meta_query().count()
        return counts

    def _heal_one(self, book: Book, real_kindle: dict | None, kindle_shelves: set[str]) -> str:
        """Settle one book's epub_meta_state; returns the counts key for the outcome."""
        assert book.root_folder is not None and book.file_path is not None  # query guarantees
        abs_path = Path(book.root_folder.path) / book.file_path

        if not abs_path.exists():
            self._record_failure(book, "file_missing")
            return "meta_failed"

        if self.epub_service.is_drm_protected(abs_path):
            book.epub_meta_state = EpubMetaState.DRM.value
            log_event("self_heal_meta_drm", book_id=book.id)
            return "meta_drm"

        if self._metadata_matches(book, self.epub_service.read_metadata(abs_path)):
            book.epub_meta_state = EpubMetaState.SYNCED.value
            book.epub_meta_synced_at = naive_utcnow()
            return "meta_verified"

        self.import_service.embed_book_metadata(book, abs_path)
        book.file_size = abs_path.stat().st_size
        book.epub_meta_state = EpubMetaState.SYNCED.value
        book.epub_meta_synced_at = naive_utcnow()
        book.epub_meta_attempts = 0
        rearm_kindle_delivery(book, real_kindle, kindle_shelves)
        return "meta_rewritten"

    def _record_failure(self, book: Book, reason: str) -> None:
        book.epub_meta_attempts += 1
        if book.epub_meta_attempts >= SELF_HEAL_META_MAX_ATTEMPTS:
            book.epub_meta_state = EpubMetaState.FAILED.value
        logger.warning(
            "Self-heal metadata failed for book %d (attempt %d): %s", book.id, book.epub_meta_attempts, reason
        )
        log_event("self_heal_meta_failed", book_id=book.id, reason=reason, attempts=book.epub_meta_attempts)

    @staticmethod
    def _metadata_matches(book: Book, meta: EpubMetadata) -> bool:
        """Narrow comparison mirroring what write_metadata embeds.

        Title exact, single-author list, series only when the DB has one.
        Description/language/publisher are deliberately not compared — HTML
        stripping and source variations would flag spurious mismatches.
        """
        if meta.title != book.title:
            return False
        if book.author is not None and meta.authors != [book.author.name]:
            return False
        if book.series_name is not None:
            if meta.series != book.series_name:
                return False
            if book.series_position is not None and meta.series_position != book.series_position:
                return False
        return True
