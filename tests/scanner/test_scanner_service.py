# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false

"""Integration tests for ScannerService — walk + read + cascade dispatch."""

from __future__ import annotations

import os
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from ebooklib import epub
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import scanner as _scanner_models  # noqa: F401  (registers tables)
from backend.models.book import Author, Book, BookStatus, RootFolder
from backend.models.scanner import DismissedScanPath, MatchProposal, MatchProposalStatus, Scan, ScanStatus
from backend.services.epub_service import EpubService
from backend.services.scanner.scanner_service import (
    MAX_EPUB_SIZE_BYTES,
    ScannerService,
    ScanProgress,
    ScanResult,
    _extract_isbn_from_identifier,
)
from backend.services.scanner.types import MatchMethod


class StubWebSocketManager:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def broadcast_sync(self, event: str, data: dict) -> None:
        self.events.append((event, data))


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db(session_factory):
    sess = session_factory()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def root_folder(db, tmp_path):
    rf = RootFolder(name="Library", path=str(tmp_path))
    db.add(rf)
    db.commit()
    db.refresh(rf)
    return rf


@pytest.fixture
def scanner(session_factory):
    return ScannerService(
        db_session_factory=session_factory,
        epub_service=EpubService(),
    )


def _write_epub(
    path: Path,
    *,
    title: str | None = "Test Title",
    author: str | None = "Test Author",
    identifier: str = "test-id",
    series: str | None = None,
    series_position: float | None = None,
) -> Path:
    book = epub.EpubBook()
    book.set_identifier(identifier)
    if title is not None:
        book.set_title(title)
    book.set_language("en")
    if author is not None:
        book.add_author(author)
    if series is not None:
        book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": series})
    if series_position is not None:
        book.add_metadata(
            None,
            "meta",
            "",
            {"name": "calibre:series_index", "content": str(series_position)},
        )

    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = "<h1>Ch1</h1><p>Body.</p>"
    book.add_item(chapter)
    book.toc = [chapter]
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(path), book, {})
    return path


def _add_book(
    db,
    *,
    hardcover_id: str,
    title: str,
    author_name: str | None = None,
    isbn: str | None = None,
    file_path: str | None = None,
    root_folder_id: int | None = None,
) -> Book:
    author = None
    if author_name is not None:
        author = db.query(Author).filter(Author.name == author_name).first()
        if author is None:
            author = Author(name=author_name)
            db.add(author)
            db.flush()

    book = Book(
        title=title,
        author_id=author.id if author else None,
        hardcover_id=hardcover_id,
        isbn=isbn,
        status=BookStatus.WANTED.value,
        file_path=file_path,
        root_folder_id=root_folder_id,
    )
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


class TestExtractIsbnHelper:
    def test_returns_none_for_none(self):
        assert _extract_isbn_from_identifier(None) is None

    def test_returns_none_for_empty(self):
        assert _extract_isbn_from_identifier("") is None

    def test_returns_none_for_non_isbn(self):
        assert _extract_isbn_from_identifier("urn:hardcover:42") is None
        assert _extract_isbn_from_identifier("test-book-001") is None

    def test_extracts_from_urn_isbn_prefix(self):
        assert _extract_isbn_from_identifier("urn:isbn:9781234567890") == "9781234567890"

    def test_extracts_from_isbn_prefix(self):
        assert _extract_isbn_from_identifier("isbn:9781234567890") == "9781234567890"

    def test_strips_hyphens_and_spaces(self):
        assert _extract_isbn_from_identifier("978-1-234-56789-0") == "9781234567890"

    def test_handles_isbn10_with_x(self):
        assert _extract_isbn_from_identifier("030640615X") == "030640615X"
        assert _extract_isbn_from_identifier("0-306-40615-x") == "030640615X"


class TestEmptyFolder:
    def test_scan_empty_folder_returns_zero_counts(self, scanner, root_folder):
        result = scanner.scan(root_folder)
        assert isinstance(result, ScanResult)
        assert result.files_seen == 0
        assert result.files_matched == 0
        assert result.files_proposed == 0
        assert result.files_unmatched == 0
        assert result.files_failed == 0
        assert result.proposals == []
        assert result.dismissed_skipped == 0


class TestWalkSemantics:
    def test_scan_finds_all_epub_files(self, scanner, root_folder, tmp_path):
        _write_epub(tmp_path / "a.epub", title="A")
        _write_epub(tmp_path / "sub" / "b.epub", title="B")
        _write_epub(tmp_path / "deep" / "nested" / "c.EPUB", title="C")

        result = scanner.scan(root_folder)
        assert result.files_seen == 3

    def test_scan_ignores_non_epub_files(self, scanner, root_folder, tmp_path):
        _write_epub(tmp_path / "real.epub")
        (tmp_path / "ignore.pdf").write_bytes(b"%PDF-fake")
        (tmp_path / "ignore.mobi").write_bytes(b"mobi-fake")
        (tmp_path / "ignore.txt").write_text("text")

        result = scanner.scan(root_folder)
        assert result.files_seen == 1

    def test_scan_skips_oversized_epub(self, scanner, root_folder, tmp_path, monkeypatch):
        _write_epub(tmp_path / "big.epub")
        _write_epub(tmp_path / "small.epub")

        real_getsize = os.path.getsize

        def fake_getsize(path):
            if str(path).endswith("big.epub"):
                return MAX_EPUB_SIZE_BYTES + 1
            return real_getsize(path)

        monkeypatch.setattr(os.path, "getsize", fake_getsize)

        result = scanner.scan(root_folder)
        assert result.files_seen == 2
        assert result.files_failed == 1
        assert result.files_unmatched == 1

    def test_scan_does_not_follow_symlinks(self, scanner, root_folder, tmp_path, tmp_path_factory):
        outside_dir = tmp_path_factory.mktemp("outside_root")
        _write_epub(outside_dir / "outside.epub")
        os.symlink(str(outside_dir), str(tmp_path / "linked"))
        _write_epub(tmp_path / "inside.epub")

        result = scanner.scan(root_folder)
        assert result.files_seen == 1


class TestDismissedPaths:
    def test_scan_skips_dismissed_paths(self, scanner, root_folder, tmp_path, db):
        _write_epub(tmp_path / "scan_me.epub")
        _write_epub(tmp_path / "skip_me.epub")
        db.add(DismissedScanPath(root_folder_id=root_folder.id, relative_path="skip_me.epub"))
        db.commit()

        result = scanner.scan(root_folder)
        assert result.files_seen == 1
        assert result.dismissed_skipped == 1


class TestCascadeIntegration:
    def test_scan_with_no_book_candidates_returns_all_unmatched(self, scanner, root_folder, tmp_path):
        _write_epub(tmp_path / "a.epub", title="A", author="X")
        _write_epub(tmp_path / "b.epub", title="B", author="Y")

        result = scanner.scan(root_folder)
        assert result.files_seen == 2
        assert result.files_unmatched == 2
        assert result.files_matched == 0
        assert result.files_proposed == 0
        assert all(p.match_result is None for p in result.proposals)

    def test_scan_auto_links_embedded_urn(self, scanner, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Foundation",
            author="Asimov",
            identifier="urn:hardcover:42",
        )
        _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")

        result = scanner.scan(root_folder)
        assert result.files_seen == 1
        assert result.files_matched == 1
        assert result.files_proposed == 0

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.method == MatchMethod.EMBEDDED_HARDCOVER_ID
        assert proposal.match_result.auto_link is True

    def test_scan_proposes_normalized_match(self, scanner, root_folder, tmp_path, db):
        _write_epub(tmp_path / "book.epub", title="Foundation", author="Asimov")
        _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")

        result = scanner.scan(root_folder)
        assert result.files_seen == 1
        assert result.files_proposed == 1
        assert result.files_matched == 0

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.method == MatchMethod.NORMALIZED_EXACT
        assert proposal.match_result.auto_link is False

    def test_scan_proposes_isbn_match(self, scanner, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Other Title",
            author="Other Author",
            identifier="urn:isbn:9781234567890",
        )
        _add_book(
            db,
            hardcover_id="42",
            title="Foundation",
            author_name="Asimov",
            isbn="978-1-234-56789-0",
        )

        result = scanner.scan(root_folder)
        assert result.files_seen == 1
        assert result.files_proposed == 1

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.method == MatchMethod.ISBN

    def test_scan_proposes_fuzzy_match(self, scanner, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Harry Potter and the Philosophers Stone",
            author="J.K. Rowling",
        )
        _add_book(
            db,
            hardcover_id="42",
            title="Harry Potter and the Philosopher's Stone",
            author_name="J.K. Rowling",
        )

        result = scanner.scan(root_folder)
        assert result.files_proposed == 1

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.method == MatchMethod.FUZZY

    def test_scan_falls_back_to_filename(self, scanner, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "Asimov - Foundation.epub",
            title=None,
            author=None,
        )
        _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")

        result = scanner.scan(root_folder)
        assert result.files_proposed == 1

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.method == MatchMethod.FILENAME


class TestErrorHandling:
    def test_scan_handles_corrupt_epub(self, scanner, root_folder, tmp_path):
        (tmp_path / "corrupt.epub").write_bytes(b"not a real epub")
        _write_epub(tmp_path / "good.epub", title="Good", author="X")

        result = scanner.scan(root_folder)
        assert result.files_seen == 2
        assert result.files_failed == 1
        assert result.files_unmatched == 1

    def test_scan_handles_drm_protected_epub(self, scanner, root_folder, tmp_path):
        target = _write_epub(tmp_path / "drm.epub")
        with zipfile.ZipFile(str(target), "a") as zf:
            zf.writestr("META-INF/encryption.xml", "<?xml version='1.0'?><encryption/>")
        _write_epub(tmp_path / "ok.epub")

        result = scanner.scan(root_folder)
        assert result.files_seen == 2
        assert result.files_failed == 1
        assert result.files_unmatched == 1


class TestProgressCallback:
    def test_scan_emits_progress_callbacks(self, session_factory, root_folder, tmp_path):
        _write_epub(tmp_path / "a.epub")
        _write_epub(tmp_path / "b.epub")

        events: list[ScanProgress] = []
        scanner = ScannerService(
            db_session_factory=session_factory,
            epub_service=EpubService(),
            progress_callback=events.append,
        )

        scanner.scan(root_folder)

        assert len(events) == 3
        assert events[-1].finished is True
        assert events[-1].current_path is None
        for ev in events[:-1]:
            assert ev.finished is False
            assert ev.current_path is not None
        assert [e.files_seen for e in events] == [1, 2, 2]

    def test_progress_callback_exception_does_not_abort_scan(self, session_factory, root_folder, tmp_path):
        _write_epub(tmp_path / "a.epub")
        _write_epub(tmp_path / "b.epub")

        def boom(_event: ScanProgress) -> None:
            raise RuntimeError("listener failed")

        scanner = ScannerService(
            db_session_factory=session_factory,
            epub_service=EpubService(),
            progress_callback=boom,
        )

        result = scanner.scan(root_folder)
        assert result.files_seen == 2


class TestNfcPaths:
    def test_scan_relative_path_is_nfc_normalized(self, scanner, root_folder, tmp_path):
        nfd_name = unicodedata.normalize("NFD", "café.epub")
        nfc_name = unicodedata.normalize("NFC", "café.epub")
        assert nfd_name != nfc_name

        _write_epub(tmp_path / nfd_name)

        result = scanner.scan(root_folder)
        assert result.files_seen == 1
        assert result.proposals[0].relative_path == nfc_name


class TestCandidateExclusion:
    def test_scan_excludes_already_linked_books_from_candidates(self, scanner, root_folder, tmp_path, db):
        rf2 = RootFolder(name="Other", path="/other")
        db.add(rf2)
        db.commit()

        _add_book(
            db,
            hardcover_id="42",
            title="Foundation",
            author_name="Asimov",
            file_path="elsewhere/foundation.epub",
            root_folder_id=int(rf2.id),
        )
        unlinked = _add_book(
            db,
            hardcover_id="43",
            title="Foundation",
            author_name="Asimov",
            file_path=None,
        )

        _write_epub(tmp_path / "found.epub", title="Foundation", author="Asimov")

        result = scanner.scan(root_folder)
        assert result.files_proposed == 1

        proposal = result.proposals[0]
        assert proposal.match_result is not None
        assert proposal.match_result.candidate_book_id == unlinked.id


class TestExecuteScanPersistence:
    def test_execute_scan_creates_scan_row(self, session_factory, root_folder, tmp_path, db):
        _write_epub(tmp_path / "book.epub", title="No Match")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        result = scanner.execute_scan(root_folder)

        scan = db.get(Scan, int(result.scan_id))
        assert scan is not None
        assert scan.status == ScanStatus.COMPLETED.value
        assert scan.finished_at is not None
        assert scan.files_seen == 1

    def test_execute_scan_persists_proposals(self, session_factory, root_folder, tmp_path, db):
        _write_epub(tmp_path / "a.epub", title="A")
        _write_epub(tmp_path / "b.epub", title="B")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        result = scanner.execute_scan(root_folder)

        proposals = db.query(MatchProposal).filter(MatchProposal.scan_id == int(result.scan_id)).all()
        assert len(proposals) == 2
        assert {proposal.relative_path for proposal in proposals} == {"a.epub", "b.epub"}

    def test_execute_scan_auto_link_updates_book(self, session_factory, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Foundation",
            author="Asimov",
            identifier="urn:hardcover:42",
        )
        book = _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        scanner.execute_scan(root_folder)

        db.refresh(book)
        assert book.file_path == "book.epub"
        assert book.root_folder_id == root_folder.id

    def test_execute_scan_marks_stale_proposals_superseded(self, session_factory, root_folder, tmp_path, db):
        old_scan = Scan(root_folder_id=root_folder.id, status=ScanStatus.COMPLETED.value, started_at=datetime.utcnow())
        db.add(old_scan)
        db.flush()
        old_proposal = MatchProposal(
            scan_id=old_scan.id,
            root_folder_id=root_folder.id,
            relative_path="old.epub",
            file_size=123,
            status=MatchProposalStatus.PENDING.value,
        )
        db.add(old_proposal)
        db.commit()

        _write_epub(tmp_path / "new.epub", title="New")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        result = scanner.execute_scan(root_folder)

        db.refresh(old_proposal)
        new_proposals = db.query(MatchProposal).filter(MatchProposal.scan_id == int(result.scan_id)).all()
        assert old_proposal.status == MatchProposalStatus.SUPERSEDED.value
        assert old_proposal.decided_at is not None
        assert len(new_proposals) == 1

    def test_execute_scan_failure_marks_scan_failed(self, session_factory, root_folder, db):
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        def boom(_root_folder):
            raise RuntimeError("walk exploded")

        scanner.scan = boom  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="walk exploded"):
            scanner.execute_scan(root_folder)

        failed_scan = db.query(Scan).order_by(Scan.id.desc()).first()
        assert failed_scan is not None
        assert failed_scan.status == ScanStatus.FAILED.value
        assert failed_scan.error_message == "walk exploded"
        assert failed_scan.finished_at is not None

    def test_execute_scan_does_not_clobber_existing_link(self, session_factory, root_folder, tmp_path, db, caplog):
        _write_epub(
            tmp_path / "new.epub",
            title="Foundation",
            author="Asimov",
            identifier="urn:hardcover:42",
        )
        book = _add_book(
            db,
            hardcover_id="42",
            title="Foundation",
            author_name="Asimov",
            file_path="X/old.epub",
            root_folder_id=root_folder.id,
        )
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        with caplog.at_level("WARNING"):
            result = scanner.execute_scan(root_folder)

        db.refresh(book)
        proposal = db.query(MatchProposal).filter(MatchProposal.scan_id == int(result.scan_id)).one()
        assert book.file_path == "X/old.epub"
        assert proposal.status == MatchProposalStatus.PENDING.value
        assert proposal.candidate_book_id == book.id
        assert result.files_matched == 0
        assert result.files_proposed == 1
        assert result.files_unmatched == 0
        assert "Auto-link skipped" in caplog.text

    def test_auto_link_proposal_status_is_auto_linked(self, session_factory, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Foundation",
            author="Asimov",
            identifier="urn:hardcover:42",
        )
        _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        result = scanner.execute_scan(root_folder)

        proposal = db.query(MatchProposal).filter(MatchProposal.scan_id == int(result.scan_id)).one()
        assert proposal.status == MatchProposalStatus.AUTO_LINKED.value

    def test_book_source_set_to_scanner_on_autolink(self, session_factory, root_folder, tmp_path, db):
        _write_epub(
            tmp_path / "book.epub",
            title="Foundation",
            author="Asimov",
            identifier="urn:hardcover:42",
        )
        book = _add_book(db, hardcover_id="42", title="Foundation", author_name="Asimov")
        scanner = ScannerService(db_session_factory=session_factory, epub_service=EpubService())

        scanner.execute_scan(root_folder)

        db.refresh(book)
        assert book.source == "scanner"

    def test_progress_callback_broadcasts_websocket_event(self, session_factory, root_folder, tmp_path):
        _write_epub(tmp_path / "a.epub", title="A")
        _write_epub(tmp_path / "b.epub", title="B")
        ws_manager = StubWebSocketManager()
        scanner = ScannerService(
            db_session_factory=session_factory,
            epub_service=EpubService(),
            ws_manager=ws_manager,
        )

        scanner.execute_scan(root_folder)

        progress_events = [data for event, data in ws_manager.events if event == "scan_progress"]
        assert len(progress_events) == 3
        assert progress_events[-1]["finished"] is True
        assert progress_events[-1]["current_path"] is None

    def test_scan_completed_event_has_duration_ms(self, session_factory, root_folder, tmp_path):
        _write_epub(tmp_path / "book.epub", title="A")
        ws_manager = StubWebSocketManager()
        scanner = ScannerService(
            db_session_factory=session_factory,
            epub_service=EpubService(),
            ws_manager=ws_manager,
        )

        scanner.execute_scan(root_folder)

        completed = [data for event, data in ws_manager.events if event == "scan_completed"]
        assert len(completed) == 1
        assert "duration_ms" in completed[0]
        assert completed[0]["duration_ms"] >= 0
