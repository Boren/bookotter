# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false, reportArgumentType=false

"""Tests for PipelineService.kick_kindle_delivery (per-book instant kick)."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Book, BookStatus, KindleDeliveryStatus, RootFolder
from backend.services.pipeline_service import PipelineService
from backend.utils.pipeline_lock import acquire_pipeline_lock
from tests.helpers import create_test_book


@pytest.fixture
def file_db_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture
def root_folder_with_file(file_db_factory, tmp_path):
    db = file_db_factory()
    rf = RootFolder(name="Test", path=str(tmp_path / "library"), folder_organization="flat")
    db.add(rf)
    db.commit()
    rf_id = rf.id
    Path(rf.path).mkdir(parents=True, exist_ok=True)
    epub_file = Path(rf.path) / "book.epub"
    epub_file.write_bytes(b"PK\x03\x04dummy epub content")
    db.close()
    return rf_id, str(epub_file.relative_to(rf.path))


def _real_kindle_config() -> dict:
    return {
        "id": "test-kindle",
        "name": "Test",
        "hostname": "kindle.local",
        "port": 22,
        "username": "root",
        "password": "",
        "ssh_key_path": "/tmp/key",
        "destination_path": "/mnt/us/books/",
    }


def _make_pending_book(db, root_folder_id, file_path):
    book = create_test_book(
        db,
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=root_folder_id,
        file_path=file_path,
    )
    book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
    book.kindle_first_pending_at = datetime.utcnow()
    db.commit()
    return book.id


def _make_service(file_db_factory, kindle_client=None, ws_manager=None):
    service = PipelineService(
        db_session_factory=file_db_factory,
        kindle_client=kindle_client,
        ws_manager=ws_manager,
    )
    service._load_config_for_delivery = lambda: {"transfer": {"folder_organization": "flat"}}
    return service


class TestKickKindleDelivery:
    def test_kick_delivers_pending_book(self, file_db_factory, root_folder_with_file):
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = True
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 100}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            result = service.kick_kindle_delivery()

        assert result == {"kindle_delivery": 1}

        verify_db = file_db_factory()
        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        assert refreshed.kindle_delivered_at is not None
        verify_db.close()

    def test_kick_defers_when_lock_held(self, file_db_factory, root_folder_with_file):
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        lock_db = file_db_factory()
        with acquire_pipeline_lock(lock_db, holder="scheduled"):
            with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
                result = service.kick_kindle_delivery()
        lock_db.close()

        assert result == {"skipped": True, "reason": "lock_held"}
        kindle_client.transfer_file.assert_not_called()

    def test_kick_defers_during_bulk_sync(self, file_db_factory, root_folder_with_file, monkeypatch):
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        _make_pending_book(db, rf_id, file_rel)
        db.close()

        import backend.api.routes.sync as sync_routes

        monkeypatch.setattr(sync_routes, "_kindle_sync_running", True)

        kindle_client = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            result = service.kick_kindle_delivery()

        assert result == {"skipped": True, "reason": "bulk_sync_running"}
        kindle_client.transfer_file.assert_not_called()

    def test_kick_never_raises(self, file_db_factory, root_folder_with_file):
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.side_effect = RuntimeError("boom")
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            result = service.kick_kindle_delivery()

        assert result == {"skipped": True, "reason": "error"}


class TestDeliveryLifecycleEvents:
    def test_started_and_delivered_events_with_progress(self, file_db_factory, root_folder_with_file):
        """IN_PROGRESS broadcasts kindle_delivery_started; transfer gets a progress callback."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = True

        def fake_transfer(progress_callback=None, **kwargs):
            assert progress_callback is not None
            progress_callback(50, 100)
            progress_callback(100, 100)
            return {"success": True, "status": "transferred", "file_size": 100}

        kindle_client.transfer_file.side_effect = fake_transfer
        ws_manager = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client, ws_manager=ws_manager)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.kick_kindle_delivery()

        events = [c[0][0] for c in ws_manager.broadcast_sync.call_args_list]
        assert "kindle_delivery_started" in events
        assert "kindle_delivery_progress" in events
        assert "kindle_delivered" in events

        started = next(c[0][1] for c in ws_manager.broadcast_sync.call_args_list if c[0][0] == "kindle_delivery_started")
        assert started["book_id"] == book_id
        assert started["book_title"]

        progress = next(
            c[0][1] for c in ws_manager.broadcast_sync.call_args_list if c[0][0] == "kindle_delivery_progress"
        )
        assert progress["book_id"] == book_id
        assert progress["bytes_total"] == 100
        assert "percentage" in progress
        assert "speed_bytes_per_sec" in progress
        assert "eta_seconds" in progress
