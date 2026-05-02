"""Tests for EPUB content verification."""

import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from backend.errors import FailureReason
from backend.models.book import Author, Book, BookStatus, FolderOrganization, RootFolder
from backend.services.epub_service import EpubService
from backend.services.import_service import ImportService
from tests.helpers import create_test_epub


def _make_root_folder(db, tmp_path: Path) -> RootFolder:
    library_path = tmp_path / "library"
    library_path.mkdir()

    root_folder = RootFolder(
        name="Test Library",
        path=str(library_path),
        folder_organization=FolderOrganization.FLAT.value,
        created_at=datetime.now(UTC),
    )
    db.add(root_folder)
    db.flush()
    return root_folder


def _make_book(
    db,
    root_folder: RootFolder,
    *,
    title: str,
    author_name: str | None,
    isbn: str | None = None,
    status: str = BookStatus.DOWNLOADING.value,
) -> Book:
    author = None
    if author_name is not None:
        author = Author(name=author_name, created_at=datetime.now(UTC))
        db.add(author)
        db.flush()

    book = Book(
        title=title,
        hardcover_id=f"test-{title.replace(' ', '-').lower()}",
        author_id=author.id if author else None,
        isbn=isbn,
        status=status,
        root_folder_id=root_folder.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    if author is not None:
        book.author = author

    db.add(book)
    db.flush()
    return book


class TestEpubVerify:
    def test_matching_epub_accepted(self, tmp_path: Path) -> None:
        service = EpubService()

        with patch.object(
            service,
            "_extract_metadata",
            return_value={"title": "Dune", "authors": ["Frank Herbert"], "isbns": []},
        ):
            book = MagicMock()
            book.title = "Dune"
            book.isbn = None
            book.author = MagicMock()
            book.author.name = "Frank Herbert"

            epub_path = tmp_path / "dune.epub"
            create_test_epub(str(epub_path), "Dune", "Frank Herbert")

            is_confident, reason = service.verify_content(epub_path, book)

        assert is_confident is True
        assert reason is None

    def test_wrong_book_warns_and_accepts(self, tmp_path: Path) -> None:
        service = EpubService()

        with patch.object(
            service,
            "_extract_metadata",
            return_value={"title": "Pride and Prejudice", "authors": ["Jane Austen"], "isbns": []},
        ):
            book = MagicMock()
            book.title = "Dune"
            book.isbn = None
            book.author = MagicMock()
            book.author.name = "Frank Herbert"

            epub_path = tmp_path / "wrong.epub"
            create_test_epub(str(epub_path), "Wrong", "Wrong Author")

            is_confident, reason = service.verify_content(epub_path, book)

        assert is_confident is False
        assert reason is not None
        assert "low_confidence" in reason

    def test_isbn_match_overrides_title_mismatch(self, tmp_path: Path) -> None:
        service = EpubService()

        with patch.object(
            service,
            "_extract_metadata",
            return_value={"title": "Different Title", "authors": [], "isbns": ["978-0-441-17271-9"]},
        ):
            book = MagicMock()
            book.title = "Dune"
            book.isbn = "978-0-441-17271-9"
            book.author = None

            epub_path = tmp_path / "book.epub"
            create_test_epub(str(epub_path), "Wrong", "Wrong Author")

            is_confident, reason = service.verify_content(epub_path, book)

        assert is_confident is True
        assert reason is None

    def test_drm_epub_skips_metadata_write(self, db_session, tmp_path: Path) -> None:
        source_epub = tmp_path / "source.epub"
        create_test_epub(str(source_epub), "Dune", "Frank Herbert")
        with zipfile.ZipFile(source_epub, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/encryption.xml", "<encryption />")

        root_folder = _make_root_folder(db_session, tmp_path)
        book = _make_book(db_session, root_folder, title="Dune", author_name="Frank Herbert")

        mock_epub = MagicMock()
        mock_epub.validate_epub.return_value = True
        mock_epub.verify_content.return_value = (True, None)
        mock_epub.is_drm_protected.return_value = True

        service = ImportService(db_session, epub_service=mock_epub)
        book_id = cast(int, book.id)

        result = service.import_book(book_id, source_epub)

        assert cast(str, result.status) == BookStatus.IN_LIBRARY.value
        assert cast(bool, result.low_confidence) is True
        assert cast(str | None, result.failure_reason) == FailureReason.IMPORT_DRM_PROTECTED.value
        mock_epub.write_metadata.assert_not_called()
