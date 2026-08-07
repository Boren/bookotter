"""Tests for backend.services.self_heal_service — pipeline rename + metadata backfill."""

import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.models.book import (
    BookStatus,
    EpubMetaState,
    EreaderDeliveryStatus,
    FolderOrganization,
    PipelineLock,
    RootFolder,
)
from backend.services.epub_service import EpubService
from backend.services.self_heal_service import SelfHealService
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_epub
from tests.test_import_service import _make_book, _make_root_folder

TEMPLATE = "{Author} - {Title}"


@pytest.fixture(autouse=True)
def _fixed_template(monkeypatch):
    cfg = {"library": {"naming_template": TEMPLATE}}
    monkeypatch.setattr("backend.services.rename_service.load_config", lambda: cfg)
    monkeypatch.setattr("backend.services.self_heal_service.load_config", lambda: cfg)


@pytest.fixture(autouse=True)
def _no_ereader(monkeypatch):
    """Default: no real E-reader configured; individual tests override."""
    for module in ("rename_service", "self_heal_service"):
        monkeypatch.setattr(f"backend.services.{module}.get_first_real_ereader", lambda config=None: None)
        monkeypatch.setattr(f"backend.services.{module}.get_ereader_sync_shelves", lambda config=None: set())


def _epub_book(
    db,
    rf: RootFolder,
    *,
    title: str,
    author_name: str,
    epub_title: str | None = None,
    epub_author: str | None = None,
    rel_path: str | None = None,
    **kwargs,
):
    """IN_LIBRARY book with a real EPUB on disk.

    Defaults to a template-conformant filename so the rename pass leaves it
    alone and tests isolate the metadata pass.
    """
    book = _make_book(db, rf, title=title, author_name=author_name, status=BookStatus.IN_LIBRARY.value, **kwargs)
    book.file_path = rel_path or f"{author_name} - {title}.epub"
    abs_path = Path(rf.path) / book.file_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    create_test_epub(str(abs_path), epub_title or title, epub_author or author_name)
    book.file_size = abs_path.stat().st_size
    db.flush()
    return book


def _add_drm_marker(epub_path: Path) -> None:
    with zipfile.ZipFile(epub_path, "a") as zf:
        zf.writestr("META-INF/encryption.xml", "<encryption/>")


class TestMetadataPass:
    def test_matching_epub_marked_synced_without_rewrite(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(db_session, rf, title="Solaris", author_name="Stanislaw Lem")
        original_bytes = (tmp_path / book.file_path).read_bytes()

        result = SelfHealService(db_session).run()

        db_session.refresh(book)
        assert book.epub_meta_state == EpubMetaState.SYNCED.value
        assert book.epub_meta_synced_at is not None
        assert (tmp_path / book.file_path).read_bytes() == original_bytes
        assert book.ereader_delivery_status is None
        assert result["meta_verified"] == 1
        assert result["meta_rewritten"] == 0

    def test_mismatched_epub_rewritten(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(
            db_session, rf, title="Solaris", author_name="Stanislaw Lem", epub_title="9780156027601_output"
        )

        result = SelfHealService(db_session).run()

        db_session.refresh(book)
        assert book.epub_meta_state == EpubMetaState.SYNCED.value
        meta = EpubService().read_metadata(tmp_path / book.file_path)
        assert meta.title == "Solaris"
        assert meta.authors == ["Stanislaw Lem"]
        assert book.file_size == (tmp_path / book.file_path).stat().st_size
        assert result["meta_rewritten"] == 1

    def test_drm_epub_marked_drm_and_never_retried(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(db_session, rf, title="Locked", author_name="Drm Author", epub_title="Wrong")
        _add_drm_marker(tmp_path / book.file_path)

        result = SelfHealService(db_session).run()

        db_session.refresh(book)
        assert book.epub_meta_state == EpubMetaState.DRM.value
        assert book.epub_meta_attempts == 0
        assert result["meta_drm"] == 1

        mock_epub = MagicMock()
        SelfHealService(db_session, epub_service=mock_epub).run()
        mock_epub.is_drm_protected.assert_not_called()
        mock_epub.read_metadata.assert_not_called()

    def test_failed_write_bounded_attempts(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Corrupt", author_name="Bad File", status=BookStatus.IN_LIBRARY.value)
        book.file_path = "Bad File - Corrupt.epub"
        (tmp_path / book.file_path).write_bytes(b"not an epub at all")
        db_session.commit()

        for expected_attempts in (1, 2, 3):
            SelfHealService(db_session).run()
            db_session.refresh(book)
            assert book.epub_meta_attempts == expected_attempts

        assert book.epub_meta_state == EpubMetaState.FAILED.value

        SelfHealService(db_session).run()
        db_session.refresh(book)
        assert book.epub_meta_attempts == 3

    def test_missing_file_counts_as_failure(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(db_session, rf, title="Ghost", author_name="No One")
        (tmp_path / book.file_path).unlink()

        SelfHealService(db_session).run()

        db_session.refresh(book)
        assert book.epub_meta_state is None
        assert book.epub_meta_attempts == 1

    def test_batch_cap(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.services.self_heal_service.SELF_HEAL_META_BATCH_SIZE", 2)
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        for i in range(3):
            _epub_book(db_session, rf, title=f"Book {i}", author_name=f"Author Cap{i}")

        first = SelfHealService(db_session).run()
        second = SelfHealService(db_session).run()

        assert first["meta_verified"] == 2
        assert first["meta_remaining"] == 1
        assert second["meta_verified"] == 1
        assert second["meta_remaining"] == 0


class TestEreaderRearm:
    @pytest.fixture(autouse=True)
    def _real_ereader(self, monkeypatch):
        for module in ("rename_service", "self_heal_service"):
            monkeypatch.setattr(
                f"backend.services.{module}.get_first_real_ereader",
                lambda config=None: {"id": "k1", "hostname": "ereader.local"},
            )
            monkeypatch.setattr(
                f"backend.services.{module}.get_ereader_sync_shelves",
                lambda config=None: {"want_to_read"},
            )

    def test_rewrite_rearms_mirror_set_book(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        pinned = _epub_book(db_session, rf, title="Pinned", author_name="Author H", epub_title="Wrong Pinned")
        pinned.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
        pinned.ereader_delivery_attempts = 2
        pinned.ereader_pinned = True
        off_shelf = _epub_book(db_session, rf, title="Off Shelf", author_name="Author I", epub_title="Wrong Off")
        off_shelf.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
        off_shelf.hardcover_status = "read"
        db_session.commit()

        SelfHealService(db_session).run()

        db_session.refresh(pinned)
        db_session.refresh(off_shelf)
        assert pinned.ereader_delivery_status == EreaderDeliveryStatus.PENDING.value
        assert pinned.ereader_delivery_attempts == 0
        assert pinned.ereader_first_pending_at is not None
        assert off_shelf.ereader_delivery_status == EreaderDeliveryStatus.DELIVERED.value

    def test_verified_match_does_not_rearm(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(db_session, rf, title="Fine", author_name="Author J")
        book.ereader_delivery_status = EreaderDeliveryStatus.DELIVERED.value
        book.ereader_pinned = True
        db_session.commit()

        SelfHealService(db_session).run()

        db_session.refresh(book)
        assert book.ereader_delivery_status == EreaderDeliveryStatus.DELIVERED.value


class TestRenamePass:
    def test_rename_applied_under_held_pipeline_lock(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _epub_book(
            db_session, rf, title="Solaris", author_name="Stanislaw Lem", rel_path="9780156027601_output.epub"
        )
        db_session.add(PipelineLock(id=1, locked_at=naive_utcnow(), run_id="pipeline", holder="scheduled"))
        db_session.commit()

        result = SelfHealService(db_session).run()

        db_session.refresh(book)
        assert result["renamed"] == 1
        assert book.file_path == "Stanislaw Lem - Solaris.epub"
        assert (tmp_path / "Stanislaw Lem - Solaris.epub").exists()
        assert not (tmp_path / "9780156027601_output.epub").exists()
        assert book.epub_meta_state == EpubMetaState.SYNCED.value
