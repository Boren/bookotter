"""Tests for the self-heal stage wired into run_pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Book, BookStatus, KindleDeliveryStatus, RootFolder
from backend.services.pipeline_service import PipelineService
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_book, create_test_epub

TEMPLATE = "{Author} - {Title}"


@pytest.fixture
def file_db_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture(autouse=True)
def _self_heal_config(monkeypatch):
    cfg = {"library": {"naming_template": TEMPLATE}}
    monkeypatch.setattr("backend.services.rename_service.load_config", lambda: cfg)
    monkeypatch.setattr("backend.services.self_heal_service.load_config", lambda: cfg)
    for module in ("rename_service", "self_heal_service"):
        monkeypatch.setattr(f"backend.services.{module}.get_first_real_kindle", lambda config=None: None)
        monkeypatch.setattr(f"backend.services.{module}.get_kindle_sync_shelves", lambda config=None: set())


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


class TestRunPipelineSelfHeal:
    def test_renamed_book_delivers_with_new_basename_in_same_run(self, file_db_factory, tmp_path):
        """Self-heal runs before kindle_delivery: one run renames, then transfers the new name."""
        library = tmp_path / "library"
        library.mkdir()
        db = file_db_factory()
        rf = RootFolder(name="Lib", path=str(library), folder_organization="flat")
        db.add(rf)
        db.commit()
        create_test_epub(str(library / "9780156027601_output.epub"), "Solaris", "Stanislaw Lem")
        book = create_test_book(
            db,
            title="Solaris",
            author_name="Stanislaw Lem",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=rf.id,
            file_path="9780156027601_output.epub",
        )
        book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
        book.kindle_first_pending_at = naive_utcnow()
        book_id = book.id
        db.commit()
        db.close()

        mock_client = MagicMock()
        mock_client.is_reachable.return_value = True
        mock_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 1}
        service = PipelineService(
            db_session_factory=file_db_factory,
            kindle_client=mock_client,
            import_service=MagicMock(),
        )
        service._load_config_for_delivery = lambda: {"transfer": {"folder_organization": "flat"}}

        with patch("backend.config.load_config", return_value={"kindles": [_real_kindle_config()]}):
            service.run_pipeline(holder="scheduled")

        delivered_path = mock_client.transfer_file.call_args.kwargs["local_path"]
        assert Path(delivered_path).name == "Stanislaw Lem - Solaris.epub"
        verify_db = file_db_factory()
        refreshed = verify_db.get(Book, book_id)
        assert refreshed.file_path == "Stanislaw Lem - Solaris.epub"
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        verify_db.close()

    def test_self_heal_throttled_to_interval(self, file_db_factory):
        service = PipelineService(db_session_factory=file_db_factory, import_service=MagicMock())

        with patch("backend.services.self_heal_service.SelfHealService") as mock_cls:
            mock_cls.return_value.run.return_value = {"renamed": 0, "meta_rewritten": 0}
            first = service.process_self_heal()
            second = service.process_self_heal()

        assert mock_cls.return_value.run.call_count == 1
        assert first == 0
        assert second == 0
