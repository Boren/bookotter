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
    )
    db_session.commit()
    return book


def _run(db_session, transfer_result: dict, emit_callback=None) -> dict:
    service = HardcoverSyncService(
        hardcover_client=MagicMock(),
        config={"transfer": {"folder_organization": "flat"}},
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

        assert result == {"transferred": 0, "skipped": 1, "failed": 0}
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        assert library_book.kindle_delivered_at is not None

    def test_transferred_marks_delivered(self, db_session, library_book):
        result = _run(db_session, {"success": True, "status": "transferred", "file_size": 5})

        assert result == {"transferred": 1, "skipped": 0, "failed": 0}
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

        assert result == {"transferred": 0, "skipped": 0, "failed": 1}
        db_session.refresh(library_book)
        assert library_book.kindle_delivery_status is None
        completed = next(c[0][1] for c in emit.call_args_list if c[0][0] == "kindle_sync_completed")
        assert completed["failed"] == 1
