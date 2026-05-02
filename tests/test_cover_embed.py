# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Tests for cover-embed logic in ImportService._embed_cover."""

import logging
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ebooklib import epub as epub_lib

from backend.services.epub_service import EpubMetadata, EpubService
from backend.services.import_service import ImportService

FIXTURES = Path(__file__).parent / "fixtures"
TEST_EPUB = FIXTURES / "test_book.epub"

JPEG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


def _make_book(book_id: int = 1, cover_url: str | None = "https://example.com/cover.jpg") -> SimpleNamespace:
    return SimpleNamespace(id=book_id, cover_url=cover_url, title="Test Book")


def _make_service() -> ImportService:
    """ImportService with no DB / WS manager — only _embed_cover is exercised here."""
    svc = ImportService.__new__(ImportService)
    svc.db = None
    svc.epub_service = EpubService()
    svc.ws_manager = None
    return svc


@pytest.fixture
def epub_no_cover(tmp_path: Path) -> Path:
    dest = tmp_path / "no_cover.epub"
    shutil.copy2(TEST_EPUB, dest)
    return dest


@pytest.fixture
def epub_with_cover(tmp_path: Path) -> Path:
    """EPUB pre-seeded with a cover so the embed-skip path can be verified."""
    dest = tmp_path / "with_cover.epub"
    shutil.copy2(TEST_EPUB, dest)
    book = epub_lib.read_epub(str(dest))
    book.set_cover("existing_cover.jpg", b"EXISTING_COVER_BYTES", create_page=False)
    EpubService()._ensure_toc_uids(book.toc)
    epub_lib.write_epub(str(dest), book, {})
    return dest


@pytest.fixture
def epub_drm(tmp_path: Path) -> Path:
    dest = tmp_path / "drm.epub"
    shutil.copy2(TEST_EPUB, dest)
    with zipfile.ZipFile(dest, "a") as zf:
        zf.writestr("META-INF/encryption.xml", "<encryption/>")
    return dest


def _count_items(path: Path) -> int:
    return len(list(epub_lib.read_epub(str(path)).get_items()))


def _has_cover_meta(path: Path) -> bool:
    book = epub_lib.read_epub(str(path))
    for ns_metadata in book.metadata.values():
        for _value, attrs in ns_metadata.get("meta", []):
            if attrs.get("name") == "cover":
                return True
    return False


def _read_cover_bytes(path: Path) -> bytes | None:
    book = epub_lib.read_epub(str(path))
    for item in book.get_items():
        if isinstance(item, epub_lib.EpubCover):
            return item.content
    return None


class TestEmbedCoverSuccess:
    def test_non_drm_no_cover_embeds_cover(self, epub_no_cover: Path, caplog) -> None:
        svc = _make_service()
        book = _make_book()

        before = _count_items(epub_no_cover)

        with patch(
            "backend.services.import_service.fetch_cover",
            return_value=(JPEG_MAGIC, "image/jpeg"),
        ):
            with caplog.at_level(logging.INFO, logger="backend.services.import_service"):
                svc._embed_cover(book, epub_no_cover)

        after = _count_items(epub_no_cover)
        assert after == before + 1, "set_cover(create_page=False) must add exactly one manifest item"
        assert _has_cover_meta(epub_no_cover), "OPF cover meta should be present after embed"
        assert _read_cover_bytes(epub_no_cover) == JPEG_MAGIC, "embedded bytes must equal fetched bytes"
        assert "embedded cover" in caplog.text.lower()


class TestEmbedCoverSkip:
    def test_drm_epub_skipped(self, epub_drm: Path, caplog) -> None:
        svc = _make_service()
        book = _make_book()
        before = _count_items(epub_drm)

        with patch("backend.services.import_service.fetch_cover") as mock_fetch:
            with caplog.at_level(logging.INFO, logger="backend.services.import_service"):
                svc._embed_cover(book, epub_drm)

        mock_fetch.assert_not_called()
        assert _count_items(epub_drm) == before
        assert "drm-protected" in caplog.text.lower()
        assert "skipping cover embed" in caplog.text.lower()

    def test_existing_cover_not_replaced(self, epub_with_cover: Path, caplog) -> None:
        svc = _make_service()
        book = _make_book()
        before = _count_items(epub_with_cover)
        before_bytes = _read_cover_bytes(epub_with_cover)
        assert before_bytes == b"EXISTING_COVER_BYTES"

        with patch(
            "backend.services.import_service.fetch_cover",
            return_value=(b"NEW_COVER", "image/jpeg"),
        ) as mock_fetch:
            with caplog.at_level(logging.INFO, logger="backend.services.import_service"):
                svc._embed_cover(book, epub_with_cover)

        mock_fetch.assert_not_called()
        assert _count_items(epub_with_cover) == before
        assert _read_cover_bytes(epub_with_cover) == before_bytes
        assert "cover already present" in caplog.text.lower()

    def test_cover_url_none_no_fetch(self, epub_no_cover: Path) -> None:
        svc = _make_service()
        book = _make_book(cover_url=None)
        before = _count_items(epub_no_cover)

        with patch("backend.services.import_service.fetch_cover") as mock_fetch:
            svc._embed_cover(book, epub_no_cover)

        mock_fetch.assert_not_called()
        assert _count_items(epub_no_cover) == before

    def test_fetch_returns_none_no_change(self, epub_no_cover: Path, caplog) -> None:
        svc = _make_service()
        book = _make_book()
        before = _count_items(epub_no_cover)

        with patch(
            "backend.services.import_service.fetch_cover",
            return_value=None,
        ):
            with caplog.at_level(logging.WARNING, logger="backend.services.import_service"):
                svc._embed_cover(book, epub_no_cover)

        assert _count_items(epub_no_cover) == before
        assert not _has_cover_meta(epub_no_cover)
        # fetch_cover already logs WARNING; _embed_cover itself stays silent on this path,
        # so no WARNING from import_service is required — what matters is no exception bubbles.

    def test_embed_failure_does_not_break_import(self, epub_no_cover: Path, caplog) -> None:
        svc = _make_service()
        book = _make_book()
        before = _count_items(epub_no_cover)

        with patch(
            "backend.services.import_service.fetch_cover",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.WARNING, logger="backend.services.import_service"):
                svc._embed_cover(book, epub_no_cover)

        assert _count_items(epub_no_cover) == before
        assert "cover embed failed" in caplog.text.lower()


class TestValidationRegression:
    def test_non_cover_write_still_strict(self, tmp_path: Path) -> None:
        """Existing write_metadata path uses default expected_item_delta=0 and must not regress."""
        dest = tmp_path / "round_trip.epub"
        shutil.copy2(TEST_EPUB, dest)

        before = _count_items(dest)

        service = EpubService()
        service.write_metadata(dest, EpubMetadata(title="Updated Title"))

        after = _count_items(dest)
        assert after == before, "non-cover writes must keep item count identical"
        assert service.read_metadata(dest).title == "Updated Title"
