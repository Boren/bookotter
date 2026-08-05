# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false, reportArgumentType=false

"""Tests for Kindle delivery state machine integration into run_pipeline (Fix 2)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import object_session, sessionmaker

from backend.database import Base
from backend.models.book import BookStatus, Download, DownloadStatus, KindleDeliveryStatus, RootFolder
from backend.services.pipeline_service import PipelineService
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_book


def _import_side_effect(book_arg, file_path):
    """Mirror real ImportService: transition + commit on the book's owning session."""
    sess = object_session(book_arg)
    book_arg.status = BookStatus.IN_LIBRARY.value
    if sess is not None:
        sess.commit()
    return True


def _import_side_effect_no_op(book_arg, file_path):
    return True


@pytest.fixture
def file_db_factory(tmp_path):
    """File-based SQLite session factory so cross-session refresh works."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield Session
    engine.dispose()


@pytest.fixture
def root_folder_with_file(file_db_factory, tmp_path):
    """RootFolder with a real EPUB file on disk."""
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


def _placeholder_kindle_config() -> dict:
    return {**_real_kindle_config(), "hostname": ""}


def _make_pending_book(db, root_folder_id, file_path, **overrides):
    book = create_test_book(
        db,
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=root_folder_id,
        file_path=file_path,
        **overrides,
    )
    book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
    book.kindle_first_pending_at = naive_utcnow()
    db.commit()
    return book.id


def _make_service(file_db_factory, kindle_client=None):
    config_for_delivery = {"transfer": {"folder_organization": "flat"}}
    service = PipelineService(
        db_session_factory=file_db_factory,
        kindle_client=kindle_client,
    )
    service._load_config_for_delivery = lambda: config_for_delivery
    return service


class TestImportingMarksPending:
    def test_pending_marking_when_real_kindle_configured(self, file_db_factory, root_folder_with_file):
        """T2.1: process_importing_books marks IN_LIBRARY books as PENDING when a real Kindle is configured."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book = create_test_book(
            db,
            status=BookStatus.IMPORTING.value,
            root_folder_id=rf_id,
            file_path=file_rel,
            hardcover_status="want_to_read",
        )
        download = Download(
            book_id=book.id,
            torrent_hash="hash" + "0" * 36,
            torrent_name="x",
            indexer_name="x",
            download_url="https://x",
            size=1,
            seeders=1,
            status=DownloadStatus.COMPLETED.value,
            file_path="/dl/x.epub",
        )
        db.add(download)
        db.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = _import_side_effect

        service = PipelineService(import_service=mock_imp, db_session_factory=file_db_factory)
        with patch(
            "backend.config.load_config",
            return_value={
                "kindles": [_real_kindle_config()],
                "pipeline": {"kindle_sync_on_import": True},
                "transfer": {"sync_shelves": {"want_to_read": True}},
            },
        ):
            service.process_importing_books()
        db.close()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert refreshed.kindle_first_pending_at is not None
        verify_db.close()

    def test_no_pending_marking_for_book_outside_sync_shelves(self, file_db_factory, root_folder_with_file):
        """A book with no Hardcover shelf (scanner/manual import) is never auto-queued."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book = create_test_book(db, status=BookStatus.IMPORTING.value, root_folder_id=rf_id, file_path=file_rel)
        download = Download(
            book_id=book.id,
            torrent_hash="hash" + "7" * 36,
            torrent_name="x",
            indexer_name="x",
            download_url="https://x",
            size=1,
            seeders=1,
            status=DownloadStatus.COMPLETED.value,
            file_path="/dl/x.epub",
        )
        db.add(download)
        db.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = _import_side_effect

        service = PipelineService(import_service=mock_imp, db_session_factory=file_db_factory)
        with patch(
            "backend.config.load_config",
            return_value={
                "kindles": [_real_kindle_config()],
                "pipeline": {"kindle_sync_on_import": True},
                "transfer": {"sync_shelves": {"want_to_read": True}},
            },
        ):
            service.process_importing_books()
        db.close()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status is None
        verify_db.close()

    def test_pending_marking_for_pinned_book_without_shelf(self, file_db_factory, root_folder_with_file):
        """A pinned book auto-queues even with no Hardcover shelf."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book = create_test_book(
            db,
            status=BookStatus.IMPORTING.value,
            root_folder_id=rf_id,
            file_path=file_rel,
            kindle_pinned=True,
        )
        download = Download(
            book_id=book.id,
            torrent_hash="hash" + "8" * 36,
            torrent_name="x",
            indexer_name="x",
            download_url="https://x",
            size=1,
            seeders=1,
            status=DownloadStatus.COMPLETED.value,
            file_path="/dl/x.epub",
        )
        db.add(download)
        db.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = _import_side_effect

        service = PipelineService(import_service=mock_imp, db_session_factory=file_db_factory)
        with patch(
            "backend.config.load_config",
            return_value={
                "kindles": [_real_kindle_config()],
                "pipeline": {"kindle_sync_on_import": True},
                "transfer": {"sync_shelves": {"want_to_read": True}},
            },
        ):
            service.process_importing_books()
        db.close()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        verify_db.close()

    def test_no_pending_marking_when_disabled(self, file_db_factory, root_folder_with_file):
        """T2.2: kindle_sync_on_import=false leaves status NULL."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book = create_test_book(db, status=BookStatus.IMPORTING.value, root_folder_id=rf_id, file_path=file_rel)
        download = Download(
            book_id=book.id,
            torrent_hash="hash" + "1" * 36,
            torrent_name="x",
            indexer_name="x",
            download_url="https://x",
            size=1,
            seeders=1,
            status=DownloadStatus.COMPLETED.value,
            file_path="/dl/x.epub",
        )
        db.add(download)
        db.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = _import_side_effect

        service = PipelineService(import_service=mock_imp, db_session_factory=file_db_factory)
        with patch(
            "backend.config.load_config",
            return_value={"kindles": [_real_kindle_config()], "pipeline": {"kindle_sync_on_import": False}},
        ):
            service.process_importing_books()
        db.close()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status is None
        verify_db.close()

    def test_no_pending_marking_when_only_placeholder_kindle(self, file_db_factory, root_folder_with_file):
        """T2.3: placeholder Kindle (empty hostname) is treated as no-Kindle — status stays NULL."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book = create_test_book(db, status=BookStatus.IMPORTING.value, root_folder_id=rf_id, file_path=file_rel)
        download = Download(
            book_id=book.id,
            torrent_hash="hash" + "2" * 36,
            torrent_name="x",
            indexer_name="x",
            download_url="https://x",
            size=1,
            seeders=1,
            status=DownloadStatus.COMPLETED.value,
            file_path="/dl/x.epub",
        )
        db.add(download)
        db.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = _import_side_effect

        service = PipelineService(import_service=mock_imp, db_session_factory=file_db_factory)
        with patch(
            "backend.config.load_config",
            return_value={"kindles": [_placeholder_kindle_config()], "pipeline": {"kindle_sync_on_import": True}},
        ):
            service.process_importing_books()
        db.close()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status is None
        verify_db.close()


class TestKindleDeliveryStateMachine:
    def test_successful_delivery_marks_delivered(self, file_db_factory, root_folder_with_file):
        """T2.4: PENDING + Kindle returns success → DELIVERED, attempts=1."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 100}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        assert refreshed.kindle_delivery_attempts == 1
        verify_db.close()

    def test_soft_failure_keeps_pending_increments_attempts(self, file_db_factory, root_folder_with_file):
        """T2.5: PENDING + Kindle returns success=False → stays PENDING, attempts increments."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.transfer_file.return_value = {"success": False, "error": "unreachable"}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()
            verify_db = file_db_factory()
            from backend.models.book import Book

            after_first = verify_db.get(Book, book_id)
            assert after_first.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
            assert after_first.kindle_delivery_attempts == 1
            verify_db.close()

            service.process_kindle_delivery_books()
            verify_db = file_db_factory()
            after_second = verify_db.get(Book, book_id)
            assert after_second.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
            assert after_second.kindle_delivery_attempts == 2
            verify_db.close()

    def test_exception_keeps_pending_increments_attempts(self, file_db_factory, root_folder_with_file):
        """T2.6: transfer_file raising exception → stays PENDING, attempts increments."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.transfer_file.side_effect = ConnectionError("ssh failed")
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert refreshed.kindle_delivery_attempts == 1
        verify_db.close()

    def test_book_with_missing_root_folder_left_pending(self, file_db_factory, root_folder_with_file):
        """T2.10: book without root_folder is left PENDING (no crash, no DELIVERED)."""
        db = file_db_factory()
        book = create_test_book(db, status=BookStatus.IN_LIBRARY.value, file_path="some/path.epub")
        book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
        book.kindle_first_pending_at = naive_utcnow()
        db.commit()
        book_id = book.id
        db.close()

        kindle_client = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        kindle_client.transfer_file.assert_not_called()
        verify_db.close()

    def test_book_with_missing_file_on_disk_left_pending(self, file_db_factory, root_folder_with_file):
        """T2.11: book whose absolute path doesn't exist is left PENDING (no crash, no transfer)."""
        rf_id, _ = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, "nonexistent.epub")
        db.close()

        kindle_client = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        kindle_client.transfer_file.assert_not_called()
        verify_db.close()

    def test_path_resolution_uses_root_folder_plus_file_path(self, file_db_factory, root_folder_with_file):
        """T2.12: Canonical relative-path-bug regression. transfer_file gets absolute path."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        _make_pending_book(db, rf_id, file_rel)
        verify_db = file_db_factory()
        rf = verify_db.get(RootFolder, rf_id)
        expected_abs = os.path.join(rf.path, file_rel)
        verify_db.close()
        db.close()

        kindle_client = MagicMock()
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 1}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        kindle_client.transfer_file.assert_called_once()
        call_kwargs = kindle_client.transfer_file.call_args.kwargs
        assert call_kwargs["local_path"] == expected_abs


class TestCrossSessionPersistence:
    def test_file_path_persists_after_import_in_fresh_session(self, file_db_factory, root_folder_with_file, tmp_path):
        """T2.13: ImportService.commit() ensures file_path/file_size are visible in a fresh session.

        This is the canonical regression test for Blocker 2. It must FAIL on the
        pre-Fix-2b codebase (where ImportService only flush()es) and pass after.
        """
        from backend.models.book import Book
        from backend.services.epub_service import EpubService
        from backend.services.import_service import ImportService

        rf_id, _ = root_folder_with_file
        source_epub = tmp_path / "source.epub"

        from tests.helpers import create_test_epub

        create_test_epub(str(source_epub), title="Persistence Test", author="Test Author")

        setup_db = file_db_factory()
        book = create_test_book(
            setup_db, title="Persistence Test", status=BookStatus.IMPORTING.value, root_folder_id=rf_id
        )
        setup_db.commit()
        book_id = book.id
        setup_db.close()

        import_db = file_db_factory()
        epub_service = EpubService()
        import_service = ImportService(db=import_db, epub_service=epub_service)
        import_service.import_book(book_id, source_epub)
        import_db.close()

        verify_db = file_db_factory()
        refreshed = verify_db.get(Book, book_id)
        assert refreshed.status == BookStatus.IN_LIBRARY.value
        assert refreshed.file_path is not None and refreshed.file_path != ""
        assert refreshed.file_size is not None and refreshed.file_size > 0
        verify_db.close()


class TestLazyKindleClient:
    def test_kindle_client_built_from_fresh_config_when_not_injected(self, file_db_factory, root_folder_with_file):
        """T2.14: When kindle_client=None in constructor, KindleClient.from_config is called per-cycle.

        Regression test for Blocker 3 (stale KindleClient after Settings change).
        """
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        service = _make_service(file_db_factory, kindle_client=None)

        captured_configs = []

        class _CapturingClient:
            def __init__(self, **kwargs):
                captured_configs.append(kwargs)

            def is_reachable(self, timeout=None):
                return True

            def transfer_file(self, **kwargs):
                return {"success": True, "status": "transferred", "file_size": 1}

        with patch(
            "backend.clients.kindle_client.KindleClient.from_config", side_effect=lambda cfg: _CapturingClient(**cfg)
        ):
            with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
                service.process_kindle_delivery_books()

        assert len(captured_configs) == 1
        assert captured_configs[0]["hostname"] == "kindle.local"

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        verify_db.close()


class TestRunPipelineIntegration:
    def test_kindle_delivery_stage_runs_via_run_pipeline(self, file_db_factory, root_folder_with_file):
        """T2.7: process_kindle_delivery_books runs as a stage of run_pipeline."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 100}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            results = service.run_pipeline(holder="manual")

        assert results.get("kindle_delivery") == 1

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        verify_db.close()


class TestReachabilityGate:
    def test_offline_skips_transfers_and_attempts(self, file_db_factory, root_folder_with_file):
        """Kindle unreachable → no transfer attempted, attempts unchanged, stays PENDING."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = False
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        kindle_client.transfer_file.assert_not_called()

        verify_db = file_db_factory()
        from backend.models.book import Book

        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert refreshed.kindle_delivery_attempts == 0
        verify_db.close()

    def test_offline_still_stamps_first_pending_at(self, file_db_factory, root_folder_with_file):
        """Bookkeeping runs while offline: a missing first_pending_at gets stamped."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        from backend.models.book import Book

        db.get(Book, book_id).kindle_first_pending_at = None
        db.commit()
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = False
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_first_pending_at is not None
        verify_db.close()

    def test_offline_still_applies_delivery_timeout(self, file_db_factory, root_folder_with_file):
        """Bookkeeping runs while offline: 14-day timeout still transitions PENDING → SKIPPED."""
        from datetime import timedelta

        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        from backend.models.book import Book

        db.get(Book, book_id).kindle_first_pending_at = naive_utcnow() - timedelta(days=15)
        db.commit()
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = False
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        verify_db = file_db_factory()
        refreshed = verify_db.get(Book, book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.SKIPPED.value
        verify_db.close()

    def test_no_work_no_probe(self, file_db_factory):
        """No PENDING and no SKIPPED books → the probe is never fired."""
        kindle_client = MagicMock()
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        kindle_client.is_reachable.assert_not_called()
        kindle_client.transfer_file.assert_not_called()

    def test_probe_fires_once_for_mixed_workload(self, file_db_factory, root_folder_with_file):
        """Multiple PENDING + SKIPPED books → exactly one probe per cycle."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        rf_path = Path(db.get(RootFolder, rf_id).path)
        extra_rels = []
        for name in ("gate-two.epub", "gate-three.epub"):
            (rf_path / name).write_bytes(b"PK\x03\x04dummy epub content")
            extra_rels.append(name)
        _make_pending_book(db, rf_id, file_rel, title="Gate Book One")
        _make_pending_book(db, rf_id, extra_rels[0], title="Gate Book Two")
        skipped_id = _make_pending_book(db, rf_id, extra_rels[1], title="Gate Book Three")
        from backend.models.book import Book

        db.get(Book, skipped_id).kindle_delivery_status = KindleDeliveryStatus.SKIPPED.value
        db.commit()
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = True
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 100}
        service = _make_service(file_db_factory, kindle_client=kindle_client)

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        assert kindle_client.is_reachable.call_count == 1
        assert kindle_client.transfer_file.call_count == 2

    def test_ws_events_emitted_for_delivery_lifecycle(self, file_db_factory, root_folder_with_file):
        """kindle_delivered on success; nothing emitted on an offline cycle."""
        rf_id, file_rel = root_folder_with_file
        db = file_db_factory()
        book_id = _make_pending_book(db, rf_id, file_rel)
        db.close()

        kindle_client = MagicMock()
        kindle_client.is_reachable.return_value = False
        ws_manager = MagicMock()
        service = PipelineService(
            db_session_factory=file_db_factory,
            kindle_client=kindle_client,
            ws_manager=ws_manager,
        )
        service._load_config_for_delivery = lambda: {"transfer": {"folder_organization": "flat"}}

        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()
        ws_manager.broadcast_sync.assert_not_called()

        kindle_client.is_reachable.return_value = True
        kindle_client.transfer_file.return_value = {"success": True, "status": "transferred", "file_size": 100}
        with patch.object(service, "_get_kindle_config", return_value=_real_kindle_config()):
            service.process_kindle_delivery_books()

        events = [c[0][0] for c in ws_manager.broadcast_sync.call_args_list]
        assert "kindle_delivered" in events
        delivered_payload = next(
            c[0][1] for c in ws_manager.broadcast_sync.call_args_list if c[0][0] == "kindle_delivered"
        )
        assert delivered_payload["book_id"] == book_id
