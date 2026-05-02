# pyright: reportArgumentType=false, reportGeneralTypeIssues=false

"""
Core ScannerService: walk a root folder, read EPUBs, dispatch the matcher cascade.

This module deliberately stops short of persistence (T17) and concurrency control
(T18). Both follow-ups will extend ScannerService by wrapping ``scan()`` with the
appropriate infrastructure:

* T17 will iterate ``ScanResult.proposals`` to write ``Scan`` + ``MatchProposal``
  rows and to flip ``Book.file_path`` for auto-linked matches.
* T18 will use ``progress_callback`` (the seam left here) to broadcast WebSocket
  events and will guard ``scan()`` with an advisory lock.

Until then, ``ScannerService`` is synchronous, holds no state across runs, and
opens exactly one DB session at the start of each scan to load the candidate
index plus the dismissed-path set; the rest of the scan is pure in-memory work.
"""

from __future__ import annotations

import logging
import os
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import joinedload

from backend.models.book import Book
from backend.models.scanner import DismissedScanPath
from backend.services.scanner.matchers import build_candidate_index, cascade_match
from backend.services.scanner.types import BookCandidate, FileMetadata, MatchResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.models.book import RootFolder
    from backend.services.epub_service import EpubService

logger = logging.getLogger(__name__)

MAX_EPUB_SIZE_BYTES = 100 * 1024 * 1024

DbSessionFactory = Callable[[], "Session"]
ProgressCallback = Callable[["ScanProgress"], None]


@dataclass(frozen=True)
class ScanProgress:
    """Snapshot of scan progress emitted to ``progress_callback``.

    ``files_matched`` counts auto-linked files (only the embedded-URN tier
    produces these). ``files_proposed`` counts files added to the review queue
    (any non-auto tier). ``files_failed`` covers EpubReadError, DRM, oversize,
    and stat failures. ``current_path`` is ``None`` on the final
    ``finished=True`` event. ``scan_id`` is a uuid4 hex in T16; T17 will
    replace it with the persisted ``Scan.id``.
    """

    scan_id: str | int
    root_folder_id: int
    files_seen: int
    files_matched: int
    files_proposed: int
    files_unmatched: int
    files_failed: int
    current_path: str | None
    finished: bool


@dataclass(frozen=True)
class ProposalDraft:
    """Pre-persistence representation of a match proposal.

    T17 will iterate these to write ``MatchProposal`` rows (and to flip
    ``Book.file_path`` when ``match_result.auto_link`` is True).
    ``relative_path`` is NFC-normalized; ``match_result`` is ``None`` when no
    cascade tier produced a hit.
    """

    relative_path: str
    file_size: int
    file_meta: FileMetadata
    match_result: MatchResult | None


@dataclass(frozen=True)
class ScanResult:
    """Final result of a scan run, returned from ``ScannerService.scan()``.

    Invariant: ``files_seen == files_matched + files_proposed + files_unmatched
    + files_failed``. ``dismissed_skipped`` is tracked separately because
    dismissed files are not "seen" by the matcher cascade — they are filtered
    out before any I/O.
    """

    scan_id: str
    root_folder_id: int
    files_seen: int
    files_matched: int
    files_proposed: int
    files_unmatched: int
    files_failed: int
    proposals: list[ProposalDraft]
    dismissed_skipped: int


def _nfc(value: str) -> str:
    """NFC-normalize a path-like string for stable cross-filesystem comparison."""
    return unicodedata.normalize("NFC", value)


def _looks_like_epub(filename: str) -> bool:
    """True when ``filename`` ends in ``.epub`` (case-insensitive)."""
    return filename.lower().endswith(".epub")


def _extract_isbn_from_identifier(identifier: str | None) -> str | None:
    """Return a cleaned ISBN if ``identifier`` carries one, else None.

    Recognised forms:

    * ``urn:isbn:<isbn>`` (with or without hyphens/spaces)
    * ``isbn:<isbn>``
    * Bare ``<isbn>`` of length 10 or 13 after digit-only cleanup

    Anything else (Hardcover URNs, UUIDs, custom strings) returns None so the
    ISBN matcher does not get a spurious bucket key to look up.
    """
    if not identifier:
        return None

    raw = identifier.strip()
    lowered = raw.lower()
    if lowered.startswith("urn:isbn:"):
        raw = raw[len("urn:isbn:") :]
    elif lowered.startswith("isbn:"):
        raw = raw[len("isbn:") :]

    cleaned = "".join(("X" if c.upper() == "X" else c) for c in raw if c.isdigit() or c.upper() == "X")
    if len(cleaned) in (10, 13):
        return cleaned
    return None


class ScannerService:
    """Walk a root folder, read EPUBs, dispatch the matcher cascade.

    Constructor injection only — no module-level state. T17 wraps ``scan()`` to
    persist results; T18 wires ``progress_callback`` to the WebSocket manager
    and guards ``scan()`` with an advisory lock. Neither is implemented here.
    """

    def __init__(
        self,
        *,
        db_session_factory: DbSessionFactory,
        epub_service: EpubService,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._session_factory = db_session_factory
        self._epub_service = epub_service
        self._progress_callback = progress_callback

    def scan(self, root_folder: RootFolder) -> ScanResult:
        """Execute one synchronous scan run and return its result.

        Walks ``root_folder.path`` once with ``followlinks=False``, reads each
        EPUB no larger than ``MAX_EPUB_SIZE_BYTES``, and dispatches every
        successful read through the matcher cascade. Skips files listed in the
        ``DismissedScanPath`` table for ``root_folder``. Failures (oversize,
        DRM, corrupt zip, EpubReadError) are logged + counted; the scan never
        aborts on a single bad file.

        Does NOT persist (T17 wraps this with the writer).
        Does NOT enforce concurrency (T18 wraps this with the lock).
        """
        scan_id = uuid.uuid4().hex
        root_folder_id = int(root_folder.id)
        root_path = str(root_folder.path)

        candidates, dismissed_set = self._load_index_inputs(root_folder_id)
        index = build_candidate_index(candidates)

        files_seen = 0
        files_matched = 0
        files_proposed = 0
        files_unmatched = 0
        files_failed = 0
        dismissed_skipped = 0
        proposals: list[ProposalDraft] = []

        for dirpath, _dirnames, filenames in os.walk(root_path, followlinks=False):
            for filename in filenames:
                if not _looks_like_epub(filename):
                    continue

                filepath = os.path.join(dirpath, filename)
                relative_path = _nfc(os.path.relpath(filepath, root_path))

                if relative_path in dismissed_set:
                    dismissed_skipped += 1
                    logger.debug("Skipping dismissed path: %s", relative_path)
                    continue

                files_seen += 1

                size_bytes = self._safe_getsize(filepath)
                if size_bytes is None:
                    files_failed += 1
                    self._emit(
                        scan_id,
                        root_folder_id,
                        files_seen,
                        files_matched,
                        files_proposed,
                        files_unmatched,
                        files_failed,
                        relative_path,
                        finished=False,
                    )
                    continue

                if size_bytes > MAX_EPUB_SIZE_BYTES:
                    logger.warning(
                        "Skipping oversized EPUB (%d bytes > %d): %s",
                        size_bytes,
                        MAX_EPUB_SIZE_BYTES,
                        filepath,
                    )
                    files_failed += 1
                    self._emit(
                        scan_id,
                        root_folder_id,
                        files_seen,
                        files_matched,
                        files_proposed,
                        files_unmatched,
                        files_failed,
                        relative_path,
                        finished=False,
                    )
                    continue

                try:
                    epub_meta = self._epub_service.read_metadata(filepath)
                except Exception as exc:
                    logger.warning("Failed to read EPUB %s: %s", filepath, exc)
                    files_failed += 1
                    self._emit(
                        scan_id,
                        root_folder_id,
                        files_seen,
                        files_matched,
                        files_proposed,
                        files_unmatched,
                        files_failed,
                        relative_path,
                        finished=False,
                    )
                    continue

                file_meta = FileMetadata(
                    relative_path=relative_path,
                    size_bytes=size_bytes,
                    title=epub_meta.title,
                    authors=tuple(epub_meta.authors),
                    identifier=epub_meta.identifier,
                    isbn=_extract_isbn_from_identifier(epub_meta.identifier),
                    series=epub_meta.series,
                    series_position=epub_meta.series_position,
                )

                match_result = cascade_match(file_meta, index)

                proposals.append(
                    ProposalDraft(
                        relative_path=relative_path,
                        file_size=size_bytes,
                        file_meta=file_meta,
                        match_result=match_result,
                    )
                )

                if match_result is None:
                    files_unmatched += 1
                elif match_result.auto_link:
                    files_matched += 1
                else:
                    files_proposed += 1

                self._emit(
                    scan_id,
                    root_folder_id,
                    files_seen,
                    files_matched,
                    files_proposed,
                    files_unmatched,
                    files_failed,
                    relative_path,
                    finished=False,
                )

        self._emit(
            scan_id,
            root_folder_id,
            files_seen,
            files_matched,
            files_proposed,
            files_unmatched,
            files_failed,
            current_path=None,
            finished=True,
        )

        return ScanResult(
            scan_id=scan_id,
            root_folder_id=root_folder_id,
            files_seen=files_seen,
            files_matched=files_matched,
            files_proposed=files_proposed,
            files_unmatched=files_unmatched,
            files_failed=files_failed,
            proposals=proposals,
            dismissed_skipped=dismissed_skipped,
        )

    def _load_index_inputs(self, root_folder_id: int) -> tuple[list[BookCandidate], set[str]]:
        """Load candidates + dismissed paths in one short-lived DB session.

        We deliberately avoid holding the session for the entire scan: the
        candidate index is a pure in-memory snapshot once built, and the walk
        loop does no DB work. Already-linked Books are still loaded (they are
        excluded inside ``build_candidate_index`` so the warning logs there
        stay accurate); filtering them out here would silently mask
        duplicate-ID collisions.
        """
        candidates: list[BookCandidate] = []
        dismissed_set: set[str] = set()

        db = self._session_factory()
        try:
            for row in db.query(DismissedScanPath).filter(DismissedScanPath.root_folder_id == root_folder_id).all():
                dismissed_set.add(_nfc(str(row.relative_path)))

            books = db.query(Book).options(joinedload(Book.author)).all()
            for book in books:
                candidates.append(
                    BookCandidate(
                        id=int(book.id),
                        hardcover_id=str(book.hardcover_id) if book.hardcover_id is not None else None,
                        isbn=str(book.isbn) if book.isbn else None,
                        title=str(book.title) if book.title is not None else "",
                        author_name=str(book.author.name) if book.author is not None else None,
                        file_path=str(book.file_path) if book.file_path else None,
                    )
                )
        finally:
            db.close()

        return candidates, dismissed_set

    @staticmethod
    def _safe_getsize(filepath: str) -> int | None:
        """Return file size, or None on OSError (e.g., race-deleted file)."""
        try:
            return os.path.getsize(filepath)
        except OSError as exc:
            logger.warning("Cannot stat %s: %s", filepath, exc)
            return None

    def _emit(
        self,
        scan_id: str,
        root_folder_id: int,
        files_seen: int,
        files_matched: int,
        files_proposed: int,
        files_unmatched: int,
        files_failed: int,
        current_path: str | None,
        *,
        finished: bool,
    ) -> None:
        """Push a progress event to the configured callback (no-op when unset).

        Exceptions raised by the callback are logged and swallowed: a misbehaving
        UI listener must never abort an in-flight scan.
        """
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(
                ScanProgress(
                    scan_id=scan_id,
                    root_folder_id=root_folder_id,
                    files_seen=files_seen,
                    files_matched=files_matched,
                    files_proposed=files_proposed,
                    files_unmatched=files_unmatched,
                    files_failed=files_failed,
                    current_path=current_path,
                    finished=finished,
                )
            )
        except Exception as exc:
            logger.warning("Progress callback raised: %s", exc)
