# pyright: reportArgumentType=false, reportAttributeAccessIssue=false

"""Integration tests for ScannerService — walk + read + cascade dispatch."""

from __future__ import annotations

import os
import unicodedata
import zipfile
from pathlib import Path

import pytest
from ebooklib import epub
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import scanner as _scanner_models  # noqa: F401  (registers tables)
from backend.models.book import Author, Book, BookStatus, RootFolder
from backend.models.scanner import DismissedScanPath
from backend.services.epub_service import EpubService
from backend.services.scanner.scanner_service import (
    MAX_EPUB_SIZE_BYTES,
    ScannerService,
    ScanProgress,
    ScanResult,
    _extract_isbn_from_identifier,
)
from backend.services.scanner.types import MatchMethod


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
