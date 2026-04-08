"""Tests for backend.services.epub_service."""

import shutil
import zipfile
from pathlib import Path

import pytest

from backend.services.epub_service import (
    EpubMetadata,
    EpubReadError,
    EpubService,
    EpubValidationError,
    EpubWriteError,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEST_EPUB = FIXTURES / "test_book.epub"
TEST_EPUB_NO_META = FIXTURES / "test_book_no_metadata.epub"


@pytest.fixture
def service() -> EpubService:
    return EpubService()


@pytest.fixture
def epub_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "book.epub"
    shutil.copy2(TEST_EPUB, dest)
    return dest


@pytest.fixture
def epub_no_meta_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "book_no_meta.epub"
    shutil.copy2(TEST_EPUB_NO_META, dest)
    return dest


class TestReadMetadata:
    def test_reads_title(self, service: EpubService) -> None:
        meta = service.read_metadata(TEST_EPUB)
        assert meta.title == "Test Book Title"

    def test_reads_author(self, service: EpubService) -> None:
        meta = service.read_metadata(TEST_EPUB)
        assert meta.authors == ["Test Author Name"]

    def test_reads_language(self, service: EpubService) -> None:
        meta = service.read_metadata(TEST_EPUB)
        assert meta.language == "en"

    def test_reads_empty_metadata_epub(self, service: EpubService) -> None:
        meta = service.read_metadata(TEST_EPUB_NO_META)
        assert meta.title is None
        assert meta.authors == []

    def test_raises_on_missing_file(self, service: EpubService, tmp_path: Path) -> None:
        with pytest.raises(EpubReadError, match="not found"):
            service.read_metadata(tmp_path / "nonexistent.epub")

    def test_raises_on_corrupt_file(self, service: EpubService, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.epub"
        corrupt.write_bytes(b"not an epub")
        with pytest.raises(EpubReadError):
            service.read_metadata(corrupt)


class TestWriteMetadata:
    def test_round_trip_title(self, service: EpubService, epub_copy: Path) -> None:
        new_title = "Updated Book Title"
        service.write_metadata(epub_copy, EpubMetadata(title=new_title))
        assert service.read_metadata(epub_copy).title == new_title

    def test_round_trip_author(self, service: EpubService, epub_copy: Path) -> None:
        new_author = "Jane Doe"
        service.write_metadata(epub_copy, EpubMetadata(authors=[new_author]))
        assert service.read_metadata(epub_copy).authors == [new_author]

    def test_round_trip_series_and_position(self, service: EpubService, epub_copy: Path) -> None:
        service.write_metadata(epub_copy, EpubMetadata(series="The Series", series_position=2.0))
        meta = service.read_metadata(epub_copy)
        assert meta.series == "The Series"
        assert meta.series_position == 2.0

    def test_write_to_different_output_path(self, service: EpubService, epub_copy: Path, tmp_path: Path) -> None:
        output = tmp_path / "output.epub"
        result = service.write_metadata(epub_copy, EpubMetadata(title="Output Title"), output_path=output)
        assert result == output
        assert output.exists()
        assert epub_copy.exists()
        assert service.read_metadata(output).title == "Output Title"

    def test_item_count_preserved_after_write(self, service: EpubService, epub_copy: Path) -> None:
        from ebooklib import epub as ebooklib_epub

        before = len(list(ebooklib_epub.read_epub(str(epub_copy), options={"ignore_ncx": True}).get_items()))
        service.write_metadata(epub_copy, EpubMetadata(title="New Title"))
        after = len(list(ebooklib_epub.read_epub(str(epub_copy), options={"ignore_ncx": True}).get_items()))
        assert before == after

    def test_raises_on_missing_file(self, service: EpubService, tmp_path: Path) -> None:
        with pytest.raises(EpubReadError, match="not found"):
            service.write_metadata(tmp_path / "ghost.epub", EpubMetadata(title="X"))

    def test_no_temp_file_left_on_success(self, service: EpubService, epub_copy: Path) -> None:
        service.write_metadata(epub_copy, EpubMetadata(title="Clean"))
        tmp_files = list(epub_copy.parent.glob("*.epub.tmp"))
        assert tmp_files == []

    def test_write_series_position_integer_stored_as_int_string(self, service: EpubService, epub_copy: Path) -> None:
        service.write_metadata(epub_copy, EpubMetadata(series_position=3.0))
        meta = service.read_metadata(epub_copy)
        assert meta.series_position == 3.0


class TestValidateEpub:
    def test_valid_epub_returns_true(self, service: EpubService) -> None:
        assert service.validate_epub(TEST_EPUB) is True

    def test_missing_file_returns_false(self, service: EpubService, tmp_path: Path) -> None:
        assert service.validate_epub(tmp_path / "missing.epub") is False

    def test_corrupt_file_returns_false(self, service: EpubService, tmp_path: Path) -> None:
        bad = tmp_path / "bad.epub"
        bad.write_bytes(b"garbage data")
        assert service.validate_epub(bad) is False

    def test_zip_without_mimetype_returns_false(self, service: EpubService, tmp_path: Path) -> None:
        fake = tmp_path / "fake.epub"
        with zipfile.ZipFile(fake, "w") as zf:
            zf.writestr("some_file.txt", "hello")
        assert service.validate_epub(fake) is False


class TestIsDrmProtected:
    def test_normal_epub_not_drm(self, service: EpubService) -> None:
        assert service.is_drm_protected(TEST_EPUB) is False

    def test_missing_file_returns_false(self, service: EpubService, tmp_path: Path) -> None:
        assert service.is_drm_protected(tmp_path / "no.epub") is False

    def test_epub_with_encryption_xml_detected_as_drm(self, service: EpubService, tmp_path: Path) -> None:
        drm_epub = tmp_path / "drm.epub"
        shutil.copy2(TEST_EPUB, drm_epub)
        with zipfile.ZipFile(drm_epub, "a") as zf:
            zf.writestr("META-INF/encryption.xml", "<encryption/>")
        assert service.is_drm_protected(drm_epub) is True

    def test_drm_epub_raises_on_read_metadata(self, service: EpubService, tmp_path: Path) -> None:
        drm_epub = tmp_path / "drm.epub"
        shutil.copy2(TEST_EPUB, drm_epub)
        with zipfile.ZipFile(drm_epub, "a") as zf:
            zf.writestr("META-INF/encryption.xml", "<encryption/>")
        with pytest.raises(EpubReadError, match="DRM"):
            service.read_metadata(drm_epub)

    def test_drm_epub_raises_on_write_metadata(self, service: EpubService, tmp_path: Path) -> None:
        drm_epub = tmp_path / "drm.epub"
        shutil.copy2(TEST_EPUB, drm_epub)
        with zipfile.ZipFile(drm_epub, "a") as zf:
            zf.writestr("META-INF/encryption.xml", "<encryption/>")
        with pytest.raises(EpubWriteError, match="DRM"):
            service.write_metadata(drm_epub, EpubMetadata(title="X"))
