"""Tests for HardcoverSyncService.run_kindle_sync: delivery marking + lifecycle events."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models.book import BookStatus, KindleDeliveryStatus, RootFolder
from backend.services.hardcover_sync_service import HardcoverSyncService
from tests.helpers import create_test_book

KINDLE_CONFIG = {
    "id": "abc123",
    "name": "My Kindle",
    "hostname": "kindle.local",
    "port": 22,
    "username": "root",
    "password": "",
    "ssh_key_path": "",
    "destination_path": "/mnt/us/books/",
}


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def library_book(db_session, tmp_path):
    """An IN_LIBRARY book with a real file on disk."""
    rf = RootFolder(name="Test", path=str(tmp_path / "library"), folder_organization="flat")
    db_session.add(rf)
    db_session.commit()
    Path(rf.path).mkdir(parents=True, exist_ok=True)
    (Path(rf.path) / "book.epub").write_bytes(b"PK\x03\x04dummy")
    book = create_test_book(
        db_session,
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=rf.id,
        file_path="book.epub",
        hardcover_status="want_to_read",
    )
    db_session.commit()
    return book


def _run(db_session, transfer_result: dict, emit_callback=None) -> dict:
    service = HardcoverSyncService(
        hardcover_client=MagicMock(),
        config={
            "transfer": {
                "folder_organization": "flat",
                "sync_shelves": {"want_to_read": True},
                "cleanup_enabled": False,
            }
        },
        emit_callback=emit_callback,
    )
    mock_client = MagicMock()
    mock_client.transfer_file.return_value = transfer_result
    with (
        patch("backend.services.hardcover_sync_service.get_kindle_by_id", return_value=KINDLE_CONFIG),
        patch("backend.services.hardcover_sync_service.KindleClient") as client_cls,
    ):
        client_cls.from_config.return_value = mock_client
        return service.run_kindle_sync("abc123", db_session)


class TestRunKindleSync:
    def test_skip_existing_marks_delivered(self, db_session, library_book):
        """A book already on the device gets kindle_delivery_status=DELIVERED persisted."""
        result = _run(db_session, {"success": True, "status": "skipped", "file_size": 0})

        assert result == {"transferred": 0, "skipped": 1, "failed": 0, "cleanup": None, "dry_run": False}
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        assert library_book.kindle_delivered_at is not None

    def test_transferred_marks_delivered(self, db_session, library_book):
        result = _run(db_session, {"success": True, "status": "transferred", "file_size": 5})

        assert result == {"transferred": 1, "skipped": 0, "failed": 0, "cleanup": None, "dry_run": False}
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        assert library_book.kindle_delivered_at is not None

    def test_per_book_delivered_event_emitted(self, db_session, library_book):
        """Bulk sync emits kindle_delivered per book so open UIs refresh live."""
        emit = MagicMock()
        _run(db_session, {"success": True, "status": "transferred", "file_size": 5}, emit_callback=emit)

        delivered = next(c[0][1] for c in emit.call_args_list if c[0][0] == "kindle_delivered")
        assert delivered == {"book_id": library_book.id, "status": "transferred"}

    def test_lifecycle_events_emitted_synchronously(self, db_session, library_book):
        """kindle_sync_started/completed reach a plain sync callback (no coroutine leak)."""
        emit = MagicMock()
        _run(db_session, {"success": True, "status": "transferred", "file_size": 5}, emit_callback=emit)

        events = [c[0][0] for c in emit.call_args_list]
        assert events[0] == "kindle_sync_started"
        assert emit.call_args_list[0][0][1] == {"kindle_id": "abc123", "total_books": 1}
        assert "kindle_sync_completed" in events
        completed = next(c[0][1] for c in emit.call_args_list if c[0][0] == "kindle_sync_completed")
        assert completed == {"transferred": 1, "skipped": 0, "failed": 0}

    def test_failed_transfer_counted(self, db_session, library_book):
        emit = MagicMock()
        result = _run(db_session, {"success": False, "error": "boom"}, emit_callback=emit)

        assert result == {"transferred": 0, "skipped": 0, "failed": 1, "cleanup": None, "dry_run": False}
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status is None
        completed = next(c[0][1] for c in emit.call_args_list if c[0][0] == "kindle_sync_completed")
        assert completed["failed"] == 1


def _run_mirror(db_session, config_transfer: dict, dry_run: bool = False, mock_client: MagicMock | None = None):
    """Run run_kindle_sync with a configurable transfer config; returns (result, mock_client)."""
    service = HardcoverSyncService(
        hardcover_client=MagicMock(),
        config={"transfer": config_transfer},
    )
    if mock_client is None:
        mock_client = MagicMock()
        mock_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 5}
        mock_client.generate_remote_path.side_effect = lambda filename, **kw: f"/mnt/us/books/{filename}"
        mock_client.cleanup_orphaned_books.return_value = {"total_orphans": 0, "deleted": 0, "failed": 0}
        mock_client.find_orphaned_books.return_value = []
        mock_client.list_all_books.return_value = []
    with (
        patch("backend.services.hardcover_sync_service.get_kindle_by_id", return_value=KINDLE_CONFIG),
        patch("backend.services.hardcover_sync_service.KindleClient") as client_cls,
    ):
        client_cls.from_config.return_value = mock_client
        result = service.run_kindle_sync("abc123", db_session, dry_run=dry_run)
    return result, mock_client


MIRROR_TRANSFER_CFG = {
    "folder_organization": "flat",
    "sync_shelves": {"want_to_read": True, "currently_reading": True, "read": False},
    "cleanup_enabled": True,
    "cleanup_sdr_folders": True,
    "cleanup_protected_paths": ["/mnt/us/books/koreader/"],
}


class TestMirrorSelection:
    def test_out_of_set_book_not_transferred(self, db_session, library_book, tmp_path):
        (Path(library_book.root_folder.path) / "other.epub").write_bytes(b"PK\x03\x04dummy")
        create_test_book(
            db_session,
            title="Scanner Book",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=library_book.root_folder_id,
            file_path="other.epub",
            isbn="978-0-999-00000-1",
        )
        db_session.commit()

        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG)

        assert result["transferred"] == 1
        transferred_paths = [c.kwargs["local_path"] for c in client.transfer_file.call_args_list]
        assert all(p.endswith("book.epub") for p in transferred_paths)

    def test_pinned_book_transferred_despite_no_shelf(self, db_session, library_book):
        (Path(library_book.root_folder.path) / "pinned.epub").write_bytes(b"PK\x03\x04dummy")
        create_test_book(
            db_session,
            title="Pinned Book",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=library_book.root_folder_id,
            file_path="pinned.epub",
            isbn="978-0-999-00000-2",
            kindle_pinned=True,
        )
        db_session.commit()

        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG)

        assert result["transferred"] == 2

    def test_book_moved_off_shelf_removed_from_mirror(self, db_session, library_book):
        library_book.hardcover_status = None
        library_book.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
        db_session.commit()
        # Another book still carries a status so the pre-backfill guard passes
        create_test_book(
            db_session,
            title="Still Wanted",
            status=BookStatus.MISSING.value,
            hardcover_status="want_to_read",
            isbn="978-0-999-00000-3",
        )
        db_session.commit()

        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG)

        client.transfer_file.assert_not_called()
        # Expected set for cleanup is empty → the delivered file is an orphan candidate
        expected_arg = client.cleanup_orphaned_books.call_args[0][0]
        assert expected_arg == []
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status is None
        assert library_book.kindle_delivered_at is None


class TestMirrorCleanup:
    def test_cleanup_called_with_expected_paths_and_options(self, db_session, library_book):
        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG)

        args, kwargs = client.cleanup_orphaned_books.call_args
        assert args[0] == ["/mnt/us/books/book.epub"]
        assert args[1] == ["/mnt/us/books/koreader/"]
        assert kwargs["delete_sdr"] is True
        assert result["cleanup"] == {"total_orphans": 0, "deleted": 0, "failed": 0}

    def test_cleanup_not_called_when_disabled(self, db_session, library_book):
        cfg = {**MIRROR_TRANSFER_CFG, "cleanup_enabled": False}
        result, client = _run_mirror(db_session, cfg)

        client.cleanup_orphaned_books.assert_not_called()
        assert result["cleanup"] is None

    def test_cleanup_skipped_before_shelf_backfill(self, db_session, library_book):
        # No book anywhere has a hardcover_status → cleanup must not run
        library_book.hardcover_status = None
        library_book.kindle_pinned = True
        db_session.commit()

        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG)

        client.cleanup_orphaned_books.assert_not_called()
        assert result["cleanup"] is None
        # The pinned book still transfers — only cleanup is gated
        assert result["transferred"] == 1


class TestDryRun:
    def test_dry_run_no_side_effects(self, db_session, library_book):
        library_book.kindle_delivery_status = None
        db_session.commit()

        result, client = _run_mirror(db_session, MIRROR_TRANSFER_CFG, dry_run=True)

        client.transfer_file.assert_not_called()
        client.cleanup_orphaned_books.assert_not_called()
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status is None
        assert result["dry_run"] is True

    def test_dry_run_reports_would_send_and_would_delete(self, db_session, library_book):
        client = MagicMock()
        client.generate_remote_path.side_effect = lambda filename, **kw: f"/mnt/us/books/{filename}"
        client.list_all_books.return_value = ["/mnt/us/books/orphan.epub"]
        client.find_orphaned_books.return_value = ["/mnt/us/books/orphan.epub"]

        result, _ = _run_mirror(db_session, MIRROR_TRANSFER_CFG, dry_run=True, mock_client=client)

        assert [b["title"] for b in result["would_send"]] == [library_book.title]
        assert result["would_delete"] == ["/mnt/us/books/orphan.epub"]

    def test_dry_run_would_send_excludes_files_already_on_device(self, db_session, library_book):
        client = MagicMock()
        client.generate_remote_path.side_effect = lambda filename, **kw: f"/mnt/us/books/{filename}"
        client.list_all_books.return_value = ["/mnt/us/books/book.epub"]
        client.find_orphaned_books.return_value = []

        result, _ = _run_mirror(db_session, MIRROR_TRANSFER_CFG, dry_run=True, mock_client=client)

        assert result["would_send"] == []
