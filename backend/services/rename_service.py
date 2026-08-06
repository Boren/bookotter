"""Bulk library renaming: Radarr-style preview and apply.

Preview and apply share one target computation so what the preview shows is
exactly what apply does. Apply runs under the pipeline lock (single writer),
moves files with atomic_move, commits the DB per file so DB and filesystem
never drift by more than the file in flight, keeps the scanner tables
consistent, and resets Kindle delivery for renamed mirror-set books — the
shelf-mirror sync derives device paths from the local basename, so the pipeline
re-sends the new name and the next sync's cleanup removes the old device file.
"""

import logging
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from backend.config import get_first_real_kindle, get_kindle_sync_shelves, load_config
from backend.constants import MAX_COLLISION_ATTEMPTS
from backend.errors import FailureReason, PipelineError
from backend.models.book import Book, BookStatus
from backend.models.scanner import DismissedScanPath, MatchProposal, MatchProposalStatus
from backend.services.import_service import ImportService
from backend.utils.atomic import atomic_move
from backend.utils.clock import naive_utcnow
from backend.utils.events import log_event
from backend.utils.kindle_delivery import rearm_kindle_delivery
from backend.utils.pipeline_lock import acquire_pipeline_lock

logger = logging.getLogger(__name__)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


@dataclass
class RenameItem:
    """One book's old -> new rename, as shown in preview and executed by apply."""

    book_id: int
    title: str
    root_folder_id: int
    old_path: str  # relative to root folder, as stored
    new_path: str  # relative, post collision-resolution
    changed: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RenameService:
    """Computes and executes library-wide renames from the naming template."""

    def __init__(self, db: Session, import_service: ImportService | None = None) -> None:
        self.db = db
        self.import_service = import_service or ImportService(db)

    def preview(self) -> list[RenameItem]:
        """Old -> new for every in-library book; no filesystem changes."""
        return self._compute_targets()

    def apply(self, book_ids: list[int] | None = None) -> dict:
        """Execute the renames, optionally limited to book_ids.

        Raises PipelineError(PIPELINE_LOCK_HELD) if the pipeline is running.
        """
        with acquire_pipeline_lock(self.db, holder="manual"):
            return self._apply_locked(book_ids)

    def apply_locked(self, book_ids: list[int] | None = None) -> dict:
        """Execute the renames; the caller must already hold the pipeline lock.

        Intended for the pipeline self-heal stage, which runs inside the
        pipeline's own lock — calling apply() there would deadlock on
        PIPELINE_LOCK_HELD.
        """
        return self._apply_locked(book_ids)

    def _compute_targets(self) -> list[RenameItem]:
        template = load_config().get("library", {}).get("naming_template")
        books = (
            self.db.query(Book)
            .options(joinedload(Book.author), joinedload(Book.root_folder))
            .filter(
                Book.status == BookStatus.IN_LIBRARY.value,
                Book.file_path.isnot(None),
                Book.root_folder_id.isnot(None),
            )
            .order_by(Book.id)
            .all()
        )

        claimed_by_root: dict[int, set[str]] = {}
        items: list[RenameItem] = []
        for book in books:
            rf = book.root_folder
            if rf is None or book.file_path is None:
                continue
            root = Path(rf.path)
            old_rel = book.file_path
            abs_old = root / old_rel
            new_rel = str(self.import_service.organize_path(book, rf, template).relative_to(root))
            claimed = claimed_by_root.setdefault(rf.id, set())

            error = None
            if not abs_old.exists():
                error = "source_missing"
            else:
                new_rel = self._resolve_target(root, abs_old, new_rel, claimed)
                claimed.add(_nfc(new_rel))

            items.append(
                RenameItem(
                    book_id=book.id,
                    title=book.title,
                    root_folder_id=rf.id,
                    old_path=old_rel,
                    new_path=new_rel,
                    changed=new_rel != old_rel,
                    error=error,
                )
            )
        return items

    @staticmethod
    def _resolve_target(root: Path, abs_old: Path, new_rel: str, claimed: set[str]) -> str:
        """Uniquify new_rel against already-claimed targets and files on disk.

        A book's own file is never a collision (allows no-ops and case-only
        renames); anything else gets the ' (1)'..' (99)' suffix treatment.
        """
        base = Path(new_rel)
        candidate = new_rel
        for i in range(1, MAX_COLLISION_ATTEMPTS + 2):
            abs_new = root / candidate
            collides = _nfc(candidate) in claimed or (abs_new.exists() and not abs_new.samefile(abs_old))
            if not collides:
                return candidate
            candidate = str(base.with_stem(f"{base.stem} ({i})"))
        raise PipelineError(
            f"Too many collisions for {new_rel} (>{MAX_COLLISION_ATTEMPTS})",
            FailureReason.IMPORT_FILE_COLLISION,
        )

    def _apply_locked(self, book_ids: list[int] | None) -> dict:
        items = self._compute_targets()
        if book_ids is not None:
            wanted = set(book_ids)
            items = [item for item in items if item.book_id in wanted]

        config = load_config()
        real_kindle = get_first_real_kindle(config)
        kindle_shelves = get_kindle_sync_shelves(config)

        renamed = skipped = failed = 0
        results: list[dict] = []
        pruned_dirs: set[tuple[Path, Path]] = set()  # (old parent, root)

        for item in items:
            entry = item.to_dict()
            if item.error is not None or not item.changed:
                skipped += 1
                entry["status"] = "skipped"
                results.append(entry)
                continue

            book = self.db.get(Book, item.book_id)
            if book is None or book.root_folder is None:
                skipped += 1
                entry["status"] = "skipped"
                entry["error"] = "book_missing"
                results.append(entry)
                continue
            root = Path(book.root_folder.path)
            abs_old = root / item.old_path
            abs_new = root / item.new_path

            try:
                atomic_move(abs_old, abs_new)
                book.file_path = item.new_path
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                failed += 1
                entry["status"] = "failed"
                entry["error"] = str(exc)
                results.append(entry)
                logger.error("Rename failed for book %d (%s): %s", item.book_id, item.old_path, exc)
                continue

            pruned_dirs.add((abs_old.parent, root))
            try:
                self._sync_bookkeeping(book, item, real_kindle, kindle_shelves)
                self.db.commit()
            except Exception as exc:  # bookkeeping must not undo a completed move
                self.db.rollback()
                logger.warning("Post-rename bookkeeping failed for book %d: %s", item.book_id, exc)

            renamed += 1
            entry["status"] = "renamed"
            results.append(entry)

        for parent, root in pruned_dirs:
            self._prune_empty_dirs(parent, root)

        log_event("library_renamed", total=len(items), renamed=renamed, skipped=skipped, failed=failed)
        return {
            "total": len(items),
            "renamed": renamed,
            "skipped": skipped,
            "failed": failed,
            "items": results,
        }

    def _sync_bookkeeping(
        self, book: Book, item: RenameItem, real_kindle: dict | None, kindle_shelves: set[str]
    ) -> None:
        """Scanner-table consistency and Kindle re-delivery for a renamed book."""
        self.db.query(MatchProposal).filter(
            MatchProposal.root_folder_id == item.root_folder_id,
            MatchProposal.relative_path == _nfc(item.old_path),
            MatchProposal.status == MatchProposalStatus.PENDING.value,
        ).update(
            {
                MatchProposal.status: MatchProposalStatus.SUPERSEDED.value,
                MatchProposal.decided_at: naive_utcnow(),
            },
            synchronize_session=False,
        )
        self.db.query(DismissedScanPath).filter(
            DismissedScanPath.root_folder_id == item.root_folder_id,
            DismissedScanPath.relative_path == _nfc(item.new_path),
        ).delete(synchronize_session=False)

        rearm_kindle_delivery(book, real_kindle, kindle_shelves)

    @staticmethod
    def _prune_empty_dirs(directory: Path, root: Path) -> None:
        """Remove now-empty directories from directory up to (never including) root."""
        current = directory
        while current != root and current.is_relative_to(root):
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
