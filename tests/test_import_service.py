"""Tests for backend.services.import_service."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.models.book import Author, Book, BookStatus, FolderOrganization, RootFolder
from backend.services.import_service import (
    BookImportError,
    ImportInvalidEpubError,
    ImportService,
    ImportStateError,
    sanitize_path_component,
)
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_epub


def _make_root_folder(db, tmp_path: Path, org: str = FolderOrganization.FLAT.value) -> RootFolder:
    rf = RootFolder(
        name="Test Library",
        path=str(tmp_path),
        folder_organization=org,
        created_at=naive_utcnow(),
    )
    db.add(rf)
    db.flush()
    return rf


_book_counter = 0


def _make_book(
    db,
    root_folder: RootFolder,
    *,
    title: str = "Test Book",
    author_name: str = None,
    status: str = BookStatus.DOWNLOADING.value,
    series_name: str | None = None,
    series_position: float | None = None,
    description: str | None = None,
) -> Book:
    global _book_counter
    if author_name is None:
        _book_counter += 1
        author_name = f"Author {_book_counter}"

    author = Author(name=author_name, created_at=naive_utcnow())
    db.add(author)
    db.flush()

    book = Book(
        title=title,
        hardcover_id=f"test-{_book_counter}",
        author_id=author.id,
        status=status,
        root_folder_id=root_folder.id,
        series_name=series_name,
        series_position=series_position,
        description=description,
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
    )
    db.add(book)
    db.flush()
    return book


@pytest.fixture
def source_epub(tmp_path: Path) -> Path:
    epub = tmp_path / "source.epub"
    create_test_epub(str(epub), "Source Book", "Source Author")
    return epub


@pytest.fixture
def lib_root(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    return lib


class TestSanitizePathComponent:
    def test_replaces_forward_slash(self) -> None:
        assert "/" not in sanitize_path_component("A/B")

    def test_replaces_backslash(self) -> None:
        assert "\\" not in sanitize_path_component("A\\B")

    def test_replaces_colon(self) -> None:
        assert ":" not in sanitize_path_component("Title: Subtitle")

    def test_replaces_asterisk(self) -> None:
        assert "*" not in sanitize_path_component("A*B")

    def test_replaces_question_mark(self) -> None:
        assert "?" not in sanitize_path_component("Why?")

    def test_replaces_double_quote(self) -> None:
        assert '"' not in sanitize_path_component('He said "hi"')

    def test_replaces_angle_brackets(self) -> None:
        result = sanitize_path_component("<tag>")
        assert "<" not in result and ">" not in result

    def test_replaces_pipe(self) -> None:
        assert "|" not in sanitize_path_component("A|B")

    def test_strips_leading_trailing_dots(self) -> None:
        assert not sanitize_path_component("..hidden").startswith(".")

    def test_strips_leading_trailing_spaces(self) -> None:
        result = sanitize_path_component("  hello  ")
        assert not result.startswith(" ") and not result.endswith(" ")

    def test_safe_name_unchanged(self) -> None:
        assert sanitize_path_component("Normal Name") == "Normal Name"

    def test_empty_result_becomes_underscore(self) -> None:
        assert sanitize_path_component("...") == "_"


class TestOrganizePath:
    def _service(self, db) -> ImportService:
        return ImportService(db, epub_service=MagicMock())

    def test_flat_puts_file_directly_under_root(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="My Book")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "My Book.epub"

    def test_author_creates_author_subdir(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR.value)
        book = _make_book(db_session, rf, title="My Book", author_name="Jane Doe")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "Jane Doe" / "My Book.epub"

    def test_series_creates_series_subdir(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.SERIES.value)
        book = _make_book(db_session, rf, title="First", series_name="Magic World")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "Magic World" / "First.epub"

    def test_series_no_series_falls_back_to_flat(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.SERIES.value)
        book = _make_book(db_session, rf, title="Standalone")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "Standalone.epub"

    def test_author_series_creates_nested_subdirs(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR_SERIES.value)
        book = _make_book(db_session, rf, title="Book 1", author_name="Jane Doe", series_name="Epic Saga")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "Jane Doe" / "Epic Saga" / "Book 1.epub"

    def test_author_series_no_series_falls_back_to_author(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR_SERIES.value)
        book = _make_book(db_session, rf, title="Solo", author_name="Jane Doe")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result == lib_root / "Jane Doe" / "Solo.epub"

    def test_no_author_uses_unknown_author(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR.value)
        book = _make_book(db_session, rf, title="Anon Book")
        book.author = None
        book.author_id = None
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert result.parent.name == "Unknown Author"

    def test_special_chars_in_title_sanitized(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Book: The Reckoning?")
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert ":" not in result.name and "?" not in result.name

    def test_special_chars_in_author_sanitized(self, db_session, lib_root: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR.value)
        book = _make_book(db_session, rf, author_name='Author "Pen" Name')
        svc = self._service(db_session)

        result = svc.organize_path(book, rf)

        assert '"' not in str(result)


class TestCopyToLibrary:
    def _service(self, db) -> ImportService:
        return ImportService(db, epub_service=MagicMock())

    def test_copies_file_to_dest(self, db_session, tmp_path: Path, source_epub: Path) -> None:
        dest = tmp_path / "lib" / "copy.epub"
        svc = self._service(db_session)

        result = svc.copy_to_library(source_epub, dest)

        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_creates_parent_directories(self, db_session, tmp_path: Path, source_epub: Path) -> None:
        dest = tmp_path / "a" / "b" / "c" / "book.epub"
        svc = self._service(db_session)

        svc.copy_to_library(source_epub, dest)

        assert dest.exists()

    def test_source_and_dest_are_independent(self, db_session, tmp_path: Path, source_epub: Path) -> None:
        dest = tmp_path / "lib" / "copy.epub"
        svc = self._service(db_session)

        svc.copy_to_library(source_epub, dest)

        assert source_epub.exists()

    def test_raises_on_missing_source(self, db_session, tmp_path: Path) -> None:
        svc = self._service(db_session)
        with pytest.raises(BookImportError, match="not found"):
            svc.copy_to_library(tmp_path / "ghost.epub", tmp_path / "dest.epub")


class TestWriteMetadata:
    def test_calls_epub_service_with_book_metadata(self, db_session, lib_root: Path) -> None:
        mock_epub = MagicMock()
        rf = _make_root_folder(db_session, lib_root)
        book = _make_book(
            db_session,
            rf,
            title="Great Book",
            author_name="Famous Writer",
            series_name="Series A",
            series_position=2.0,
            description="A great read.",
        )
        svc = ImportService(db_session, epub_service=mock_epub)

        svc.write_metadata(book, lib_root / "book.epub")

        mock_epub.write_metadata.assert_called_once()
        call_args = mock_epub.write_metadata.call_args
        meta = call_args[0][1]
        assert meta.title == "Great Book"
        assert meta.authors == ["Famous Writer"]
        assert meta.series == "Series A"
        assert meta.series_position == 2.0
        assert meta.description == "A great read."

    def test_no_author_results_in_empty_authors_list(self, db_session, lib_root: Path) -> None:
        mock_epub = MagicMock()
        rf = _make_root_folder(db_session, lib_root)
        book = _make_book(db_session, rf, title="Anon")
        book.author = None
        svc = ImportService(db_session, epub_service=mock_epub)

        svc.write_metadata(book, lib_root / "book.epub")

        meta = mock_epub.write_metadata.call_args[0][1]
        assert meta.authors == []

    def test_raises_import_error_on_epub_service_failure(self, db_session, lib_root: Path) -> None:
        mock_epub = MagicMock()
        mock_epub.write_metadata.side_effect = Exception("EPUB write failed")
        rf = _make_root_folder(db_session, lib_root)
        book = _make_book(db_session, rf)
        svc = ImportService(db_session, epub_service=mock_epub)

        with pytest.raises(BookImportError, match="Failed to write metadata"):
            svc.write_metadata(book, lib_root / "book.epub")

    def test_strips_html_from_description_in_metadata(self, db_session, lib_root: Path) -> None:
        mock_epub = MagicMock()
        rf = _make_root_folder(db_session, lib_root)
        html_desc = "<p>Hello <b>world</b>!</p><br/>&amp; more"
        book = _make_book(
            db_session,
            rf,
            title="HTML Book",
            description=html_desc,
        )
        svc = ImportService(db_session, epub_service=mock_epub)

        svc.write_metadata(book, lib_root / "book.epub")

        mock_epub.write_metadata.assert_called_once()
        call_args = mock_epub.write_metadata.call_args
        meta = call_args[0][1]
        # Verify HTML is stripped and entities are decoded
        assert meta.description == "Hello world!\n\n& more"
        # Verify DB Book.description still has raw HTML
        assert book.description == html_desc


class TestImportBook:
    def test_successful_import_flat(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="My Book", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        result = svc.import_book(book.id, source_epub)

        assert result.status == BookStatus.IN_LIBRARY.value
        assert result.file_path is not None
        assert result.file_size is not None and result.file_size > 0

    def test_successful_import_author_org(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR.value)
        book = _make_book(db_session, rf, title="Novel", author_name="Jane Doe", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        svc.import_book(book.id, source_epub)

        expected = lib_root / "Jane Doe" / "Novel.epub"
        assert expected.exists()

    def test_successful_import_series_org(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.SERIES.value)
        book = _make_book(
            db_session,
            rf,
            title="Part One",
            series_name="The Chronicles",
            status=BookStatus.DOWNLOADING.value,
        )
        svc = ImportService(db_session)

        svc.import_book(book.id, source_epub)

        expected = lib_root / "The Chronicles" / "Part One.epub"
        assert expected.exists()

    def test_successful_import_author_series_org(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR_SERIES.value)
        book = _make_book(
            db_session,
            rf,
            title="Episode I",
            author_name="Sci Writer",
            series_name="Space Opera",
            status=BookStatus.DOWNLOADING.value,
        )
        svc = ImportService(db_session)

        svc.import_book(book.id, source_epub)

        expected = lib_root / "Sci Writer" / "Space Opera" / "Episode I.epub"
        assert expected.exists()

    def test_file_path_is_relative_to_root(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.AUTHOR.value)
        book = _make_book(
            db_session, rf, title="Relative Test", author_name="Auth", status=BookStatus.DOWNLOADING.value
        )
        svc = ImportService(db_session)

        result = svc.import_book(book.id, source_epub)

        assert not Path(result.file_path).is_absolute()
        assert (lib_root / result.file_path).exists()

    def test_book_already_in_importing_state_continues(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Retry Book", status=BookStatus.IMPORTING.value)
        svc = ImportService(db_session)

        result = svc.import_book(book.id, source_epub)

        assert result.status == BookStatus.IN_LIBRARY.value

    def test_raises_on_missing_book(self, db_session, source_epub: Path) -> None:
        svc = ImportService(db_session)
        with pytest.raises(ImportStateError, match="not found"):
            svc.import_book(99999, source_epub)

    def test_raises_on_book_without_root_folder(self, db_session, source_epub: Path) -> None:
        author = Author(name="Orphan Author", created_at=naive_utcnow())
        db_session.add(author)
        db_session.flush()
        book = Book(
            title="Orphan",
            hardcover_id="test-orphan",
            author_id=author.id,
            status=BookStatus.DOWNLOADING.value,
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
        )
        db_session.add(book)
        db_session.flush()
        svc = ImportService(db_session)

        with pytest.raises(ImportStateError, match="no root folder"):
            svc.import_book(book.id, source_epub)

    def test_raises_on_invalid_epub(self, db_session, lib_root: Path, tmp_path: Path) -> None:
        bad_epub = tmp_path / "bad.epub"
        bad_epub.write_bytes(b"not an epub")
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        with pytest.raises(ImportInvalidEpubError):
            svc.import_book(book.id, bad_epub)

    def test_duplicate_destination_creates_versioned_copy(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Dup Book", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        svc.import_book(book.id, source_epub)
        assert (lib_root / "Dup Book.epub").exists()

        book2 = _make_book(db_session, rf, title="Dup Book", status=BookStatus.DOWNLOADING.value)
        result = svc.import_book(book2.id, source_epub)

        assert result.file_path == "Dup Book (1).epub"
        assert (lib_root / "Dup Book (1).epub").exists()
        assert (lib_root / "Dup Book.epub").exists()

    def test_invalid_state_transition_raises(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Wrong State", status=BookStatus.WANTED.value)
        svc = ImportService(db_session)

        with pytest.raises(ImportStateError, match="Cannot transition"):
            svc.import_book(book.id, source_epub)

    def test_failed_import_sets_status_to_failed(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Fail Book", status=BookStatus.DOWNLOADING.value)

        mock_epub = MagicMock()
        mock_epub.validate_epub.return_value = True
        mock_epub.verify_content.return_value = (True, None)
        mock_epub.is_drm_protected.return_value = False
        mock_epub.write_metadata.side_effect = Exception("Metadata error")
        svc = ImportService(db_session, epub_service=mock_epub)

        with pytest.raises(BookImportError):
            svc.import_book(book.id, source_epub)

        assert book.status == BookStatus.FAILED.value

    def test_source_file_preserved_after_import(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Preserve Test", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        svc.import_book(book.id, source_epub)

        assert source_epub.exists()


class TestImportRootFolderFallback:
    def _make_book_without_root_folder(self, db, title: str = "No Folder Book") -> Book:
        global _book_counter
        _book_counter += 1
        author = Author(name=f"Fallback Author {_book_counter}", created_at=naive_utcnow())
        db.add(author)
        db.flush()
        book = Book(
            title=title,
            hardcover_id=f"test-fallback-{_book_counter}",
            author_id=author.id,
            status=BookStatus.DOWNLOADING.value,
            root_folder_id=None,
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
        )
        db.add(book)
        db.flush()
        return book

    def test_falls_back_to_first_root_folder(self, db_session, lib_root: Path, source_epub: Path) -> None:
        rf = _make_root_folder(db_session, lib_root, FolderOrganization.FLAT.value)
        book = self._make_book_without_root_folder(db_session)
        svc = ImportService(db_session)

        result = svc.import_book(book.id, source_epub)

        assert result.status == BookStatus.IN_LIBRARY.value
        assert result.root_folder_id == rf.id
        assert (lib_root / "No Folder Book.epub").exists()

    def test_uses_lowest_id_root_folder_when_multiple(self, db_session, tmp_path: Path, source_epub: Path) -> None:
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        rf_first = _make_root_folder(db_session, first_root, FolderOrganization.FLAT.value)
        _make_root_folder(db_session, second_root, FolderOrganization.FLAT.value)
        book = self._make_book_without_root_folder(db_session, title="Ordered Book")
        svc = ImportService(db_session)

        result = svc.import_book(book.id, source_epub)

        assert result.root_folder_id == rf_first.id
        assert (first_root / "Ordered Book.epub").exists()

    def test_raises_when_no_root_folders_exist(self, db_session, source_epub: Path) -> None:
        book = self._make_book_without_root_folder(db_session, title="Truly Homeless")
        svc = ImportService(db_session)

        with pytest.raises(ImportStateError, match="no root folder"):
            svc.import_book(book.id, source_epub)
