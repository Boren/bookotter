from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_service import PIPELINE_INTERVAL_SECONDS, PipelineService, _guid_to_hash
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def make_service(db_session, search_service=None, download_service=None, import_service=None):
    def factory():
        return db_session

    return PipelineService(
        search_service=search_service,
        download_service=download_service,
        import_service=import_service,
        db_session_factory=factory,
    )


def get_book(db, book_id):
    db.expire_all()
    return db.get(Book, book_id)


def get_download(db, download_id):
    db.expire_all()
    return db.get(Download, download_id)


def make_search_result(guid="guid-1", title="Book.epub", indexer="TestIndexer", seeders=10, size=5_000_000):
    return {
        "guid": guid,
        "title": title,
        "indexer": indexer,
        "seeders": seeders,
        "size": size,
        "download_url": "https://example.com/torrent/1",
        "magnet_url": None,
    }


class TestGuidToHash:
    def test_returns_32_char_hex(self):
        result = _guid_to_hash("some-guid")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        assert _guid_to_hash("same") == _guid_to_hash("same")

    def test_different_guids_produce_different_hashes(self):
        assert _guid_to_hash("a") != _guid_to_hash("b")

    def test_none_returns_non_empty_string(self):
        result = _guid_to_hash(None)
        assert len(result) == 32


class TestProcessWantedBooks:
    def test_no_search_service_returns_zero(self, db_session):
        service = make_service(db_session)
        assert service.process_wanted_books() == 0

    def test_empty_db_returns_zero(self, db_session):
        mock_search = MagicMock()
        service = make_service(db_session, search_service=mock_search)
        assert service.process_wanted_books() == 0
        mock_search.search_book.assert_not_called()

    def test_grabs_wanted_book_with_results(self, db_session):
        book = create_test_book(db_session, title="Dune", author_name="Frank Herbert")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result()]
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 1
        assert get_book(db_session, book_id).status == BookStatus.GRABBED

    def test_creates_download_record(self, db_session):
        book = create_test_book(db_session, title="Dune")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(guid="test-guid", seeders=5)]
        service = make_service(db_session, search_service=mock_search)

        service.process_wanted_books()

        fresh = get_book(db_session, book_id)
        assert len(fresh.downloads) == 1
        dl = fresh.downloads[0]
        assert dl.status == DownloadStatus.QUEUED
        assert dl.torrent_hash == _guid_to_hash("test-guid")
        assert dl.seeders == 5

    def test_transitions_via_searching(self, db_session):
        book = create_test_book(db_session, title="Dune")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        captured_statuses = []

        def capture_and_return(title, author):
            captured_statuses.append(get_book(db_session, book_id).status)
            return [make_search_result()]

        mock_search.search_book.side_effect = capture_and_return
        service = make_service(db_session, search_service=mock_search)

        service.process_wanted_books()

        assert BookStatus.SEARCHING in captured_statuses

    def test_increments_search_attempts(self, db_session):
        book = create_test_book(db_session, title="Dune")
        book.search_attempts = 2
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result()]
        service = make_service(db_session, search_service=mock_search)
        service.process_wanted_books()

        assert get_book(db_session, book_id).search_attempts == 3

    def test_fails_book_when_no_results(self, db_session):
        book = create_test_book(db_session, title="Nonexistent Book")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = []
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED

    def test_fails_book_on_search_exception(self, db_session):
        book = create_test_book(db_session, title="Error Book")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.side_effect = RuntimeError("Prowlarr down")
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED

    def test_processes_multiple_books(self, db_session):
        book1 = create_test_book(db_session, title="Book A")
        book2 = create_test_book(db_session, title="Book B")
        db_session.commit()
        id1, id2 = book1.id, book2.id

        mock_search = MagicMock()
        mock_search.search_book.side_effect = [
            [make_search_result(guid="guid-1")],
            [make_search_result(guid="guid-2")],
        ]
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 2
        assert get_book(db_session, id1).status == BookStatus.GRABBED
        assert get_book(db_session, id2).status == BookStatus.GRABBED

    def test_only_processes_wanted_books(self, db_session):
        create_test_book(db_session, title="Wanted")
        already_grabbed = create_test_book(db_session, title="Already Grabbed")
        already_grabbed.status = BookStatus.GRABBED
        db_session.commit()

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result()]
        service = make_service(db_session, search_service=mock_search)

        service.process_wanted_books()

        assert mock_search.search_book.call_count == 1

    def test_sets_last_searched_at(self, db_session):
        book = create_test_book(db_session, title="Dune")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = []
        service = make_service(db_session, search_service=mock_search)
        service.process_wanted_books()

        assert get_book(db_session, book_id).last_searched_at is not None


class TestProcessSearchingBooks:
    def test_no_search_service_returns_zero(self, db_session):
        service = make_service(db_session)
        assert service.process_searching_books() == 0

    def test_grabs_searching_book(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.SEARCHING)
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result()]
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_searching_books()

        assert grabbed == 1
        assert get_book(db_session, book_id).status == BookStatus.GRABBED

    def test_ignores_wanted_books(self, db_session):
        create_test_book(db_session, title="Wanted Book")
        db_session.commit()

        mock_search = MagicMock()
        service = make_service(db_session, search_service=mock_search)
        service.process_searching_books()

        mock_search.search_book.assert_not_called()


class TestProcessGrabbedBooks:
    def test_no_download_service_returns_zero(self, db_session):
        service = make_service(db_session)
        assert service.process_grabbed_books() == 0

    def test_adds_torrent_and_transitions_to_downloading(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.GRABBED)
        download = Download(
            book_id=book.id,
            torrent_hash="abc123def456abc100",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent",
            size=5_000_000,
            seeders=10,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_dl = MagicMock()
        mock_dl.add_torrent.return_value = True
        service = make_service(db_session, download_service=mock_dl)

        started = service.process_grabbed_books()

        assert started == 1
        assert get_book(db_session, book_id).status == BookStatus.DOWNLOADING
        assert get_download(db_session, dl_id).status == DownloadStatus.DOWNLOADING

    def test_fails_book_when_add_torrent_returns_false(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.GRABBED)
        download = Download(
            book_id=book.id,
            torrent_hash="failhash1234567890ab",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent",
            size=0,
            seeders=0,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_dl = MagicMock()
        mock_dl.add_torrent.return_value = False
        service = make_service(db_session, download_service=mock_dl)

        started = service.process_grabbed_books()

        assert started == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED
        assert get_download(db_session, dl_id).status == DownloadStatus.FAILED

    def test_fails_book_when_no_queued_downloads(self, db_session):
        book = create_test_book(db_session, title="Orphan", status=BookStatus.GRABBED)
        db_session.commit()
        book_id = book.id

        mock_dl = MagicMock()
        service = make_service(db_session, download_service=mock_dl)

        started = service.process_grabbed_books()

        assert started == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED
        mock_dl.add_torrent.assert_not_called()

    def test_fails_book_on_add_torrent_exception(self, db_session):
        book = create_test_book(db_session, title="Error", status=BookStatus.GRABBED)
        download = Download(
            book_id=book.id,
            torrent_hash="errhash123456789ab0",
            torrent_name="Error.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent",
            size=0,
            seeders=0,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_dl = MagicMock()
        mock_dl.add_torrent.side_effect = ConnectionError("qBit unreachable")
        service = make_service(db_session, download_service=mock_dl)

        started = service.process_grabbed_books()

        assert started == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED
        assert get_download(db_session, dl_id).status == DownloadStatus.FAILED
        assert "qBit unreachable" in get_download(db_session, dl_id).error_message


class TestProcessDownloadingBooks:
    def test_no_download_service_returns_zero(self, db_session):
        service = make_service(db_session)
        assert service.process_downloading_books() == 0

    def test_transitions_to_importing_when_complete(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.DOWNLOADING)
        download = Download(
            book_id=book.id,
            torrent_hash="donehash12345678ab0",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=5_000_000,
            seeders=10,
            status=DownloadStatus.DOWNLOADING,
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_dl = MagicMock()
        mock_dl.get_completed_file_path.return_value = "/downloads/Dune.epub"
        service = make_service(db_session, download_service=mock_dl)

        importing_count = service.process_downloading_books()

        assert importing_count == 1
        assert get_book(db_session, book_id).status == BookStatus.IMPORTING
        fresh_dl = get_download(db_session, dl_id)
        assert fresh_dl.status == DownloadStatus.COMPLETED
        assert fresh_dl.file_path == "/downloads/Dune.epub"
        assert fresh_dl.completed_at is not None

    def test_skips_book_when_still_downloading(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.DOWNLOADING)
        download = Download(
            book_id=book.id,
            torrent_hash="activehash1234567ab",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=5_000_000,
            seeders=10,
            status=DownloadStatus.DOWNLOADING,
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_dl = MagicMock()
        mock_dl.get_completed_file_path.return_value = None
        service = make_service(db_session, download_service=mock_dl)

        importing_count = service.process_downloading_books()

        assert importing_count == 0
        assert get_book(db_session, book_id).status == BookStatus.DOWNLOADING

    def test_fails_when_no_active_downloads(self, db_session):
        book = create_test_book(db_session, title="Orphan", status=BookStatus.DOWNLOADING)
        db_session.commit()
        book_id = book.id

        mock_dl = MagicMock()
        service = make_service(db_session, download_service=mock_dl)

        service.process_downloading_books()

        assert get_book(db_session, book_id).status == BookStatus.FAILED

    def test_fails_on_exception(self, db_session):
        book = create_test_book(db_session, title="Error", status=BookStatus.DOWNLOADING)
        download = Download(
            book_id=book.id,
            torrent_hash="exhash123456789ab10",
            torrent_name="Error.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=0,
            seeders=0,
            status=DownloadStatus.DOWNLOADING,
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_dl = MagicMock()
        mock_dl.get_completed_file_path.side_effect = RuntimeError("qBit API error")
        service = make_service(db_session, download_service=mock_dl)

        service.process_downloading_books()

        assert get_book(db_session, book_id).status == BookStatus.FAILED


class TestProcessImportingBooks:
    def test_no_import_service_returns_zero(self, db_session):
        service = make_service(db_session)
        assert service.process_importing_books() == 0

    def test_imports_and_transitions_to_in_library(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="imphash1234567890ab",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=5_000_000,
            seeders=10,
            status=DownloadStatus.COMPLETED,
            file_path="/downloads/Dune.epub",
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_imp = MagicMock()
        mock_imp.import_epub.return_value = True
        service = make_service(db_session, import_service=mock_imp)

        imported = service.process_importing_books()

        assert imported == 1
        assert get_book(db_session, book_id).status == BookStatus.IN_LIBRARY
        assert get_download(db_session, dl_id).status == DownloadStatus.IMPORTED

    def test_import_epub_called_with_file_path(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="argshash12345678901",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=0,
            seeders=0,
            status=DownloadStatus.COMPLETED,
            file_path="/downloads/Dune.epub",
        )
        db_session.add(download)
        db_session.commit()

        mock_imp = MagicMock()
        mock_imp.import_epub.return_value = True
        service = make_service(db_session, import_service=mock_imp)
        service.process_importing_books()

        assert mock_imp.import_epub.call_args[0][1] == "/downloads/Dune.epub"

    def test_fails_when_import_returns_false(self, db_session):
        book = create_test_book(db_session, title="Dune", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="failimphash12345678",
            torrent_name="Dune.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=0,
            seeders=0,
            status=DownloadStatus.COMPLETED,
            file_path="/downloads/Dune.epub",
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.return_value = False
        service = make_service(db_session, import_service=mock_imp)

        imported = service.process_importing_books()

        assert imported == 0
        assert get_book(db_session, book_id).status == BookStatus.FAILED

    def test_fails_when_no_completed_downloads(self, db_session):
        book = create_test_book(db_session, title="Orphan", status=BookStatus.IMPORTING)
        db_session.commit()
        book_id = book.id

        mock_imp = MagicMock()
        service = make_service(db_session, import_service=mock_imp)
        service.process_importing_books()

        assert get_book(db_session, book_id).status == BookStatus.FAILED
        mock_imp.import_epub.assert_not_called()

    def test_fails_when_no_file_path(self, db_session):
        book = create_test_book(db_session, title="NoPath", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="nopathash1234567890",
            torrent_name="NoPath.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=0,
            seeders=0,
            status=DownloadStatus.COMPLETED,
            file_path=None,
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_imp = MagicMock()
        service = make_service(db_session, import_service=mock_imp)
        service.process_importing_books()

        assert get_book(db_session, book_id).status == BookStatus.FAILED
        mock_imp.import_epub.assert_not_called()

    def test_fails_on_exception(self, db_session):
        book = create_test_book(db_session, title="Error", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="errimporthash123456",
            torrent_name="Error.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com",
            size=0,
            seeders=0,
            status=DownloadStatus.COMPLETED,
            file_path="/downloads/Error.epub",
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_imp = MagicMock()
        mock_imp.import_epub.side_effect = IOError("Disk full")
        service = make_service(db_session, import_service=mock_imp)
        service.process_importing_books()

        assert get_book(db_session, book_id).status == BookStatus.FAILED


class TestRunPipeline:
    def test_runs_all_stages_and_returns_counts(self, db_session):
        service = make_service(db_session)
        results = service.run_pipeline()

        assert set(results.keys()) == {"wanted", "searching", "grabbed", "downloading", "importing"}

    def test_stage_exception_does_not_abort_pipeline(self, db_session):
        service = make_service(db_session)
        service.process_wanted_books = MagicMock(side_effect=RuntimeError("boom"))
        service.process_searching_books = MagicMock(return_value=0)
        service.process_grabbed_books = MagicMock(return_value=0)
        service.process_downloading_books = MagicMock(return_value=0)
        service.process_importing_books = MagicMock(return_value=0)

        results = service.run_pipeline()

        assert results["wanted"] == 0
        service.process_searching_books.assert_called_once()
        service.process_grabbed_books.assert_called_once()

    def test_full_pipeline_flow(self, db_session):
        book = create_test_book(db_session, title="Dune", author_name="Frank Herbert")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(guid="dune-guid")]

        mock_dl = MagicMock()
        mock_dl.add_torrent.return_value = True
        mock_dl.get_completed_file_path.return_value = "/downloads/Dune.epub"

        mock_imp = MagicMock()
        mock_imp.import_epub.return_value = True

        service = make_service(
            db_session, search_service=mock_search, download_service=mock_dl, import_service=mock_imp
        )

        results = service.run_pipeline()

        assert results["wanted"] == 1
        assert results["grabbed"] == 1
        assert results["downloading"] == 1
        assert results["importing"] == 1
        assert get_book(db_session, book_id).status == BookStatus.IN_LIBRARY


class TestStartMonitoring:
    def test_start_monitoring_creates_and_starts_scheduler(self, db_session):
        service = make_service(db_session)
        with patch("backend.services.pipeline_service.AsyncIOScheduler") as MockScheduler:
            mock_sched = MagicMock()
            mock_sched.running = False
            MockScheduler.return_value = mock_sched

            service.start_monitoring()

            MockScheduler.assert_called_once()
            mock_sched.start.assert_called_once()
            assert service._scheduler is mock_sched

    def test_start_monitoring_adds_pipeline_job(self, db_session):
        service = make_service(db_session)
        with patch("backend.services.pipeline_service.AsyncIOScheduler") as MockScheduler:
            mock_sched = MagicMock()
            mock_sched.running = False
            MockScheduler.return_value = mock_sched

            service.start_monitoring()

            mock_sched.add_job.assert_called_once()
            call_args = mock_sched.add_job.call_args
            assert call_args[0][0] == service.run_pipeline
            assert call_args[1]["id"] == "pipeline_all_stages"

    def test_start_monitoring_is_idempotent(self, db_session):
        service = make_service(db_session)
        with patch("backend.services.pipeline_service.AsyncIOScheduler") as MockScheduler:
            mock_sched = MagicMock()
            mock_sched.running = True
            MockScheduler.return_value = mock_sched
            service._scheduler = mock_sched

            service.start_monitoring()
            service.start_monitoring()

            MockScheduler.assert_not_called()

    def test_pipeline_interval_is_15_seconds(self):
        assert PIPELINE_INTERVAL_SECONDS == 15

    def test_stop_monitoring_shuts_down_scheduler(self, db_session):
        service = make_service(db_session)
        mock_sched = MagicMock()
        mock_sched.running = True
        service._scheduler = mock_sched

        service.stop_monitoring()

        mock_sched.shutdown.assert_called_once_with(wait=False)

    def test_stop_monitoring_when_not_started_is_safe(self, db_session):
        service = make_service(db_session)
        service.stop_monitoring()

    def test_scheduler_uses_coalesce_and_single_instance(self, db_session):
        service = make_service(db_session)
        with patch("backend.services.pipeline_service.AsyncIOScheduler") as MockScheduler:
            mock_sched = MagicMock()
            mock_sched.running = False
            MockScheduler.return_value = mock_sched

            service.start_monitoring()

            init_kwargs = MockScheduler.call_args[1]
            assert init_kwargs["job_defaults"]["coalesce"] is True
            assert init_kwargs["job_defaults"]["max_instances"] == 1


class TestConcurrentProcessing:
    def test_processes_multiple_books_independently(self, db_session):
        books = [create_test_book(db_session, title=f"Book {i}") for i in range(5)]
        db_session.commit()
        book_ids = [b.id for b in books]

        mock_search = MagicMock()
        mock_search.search_book.side_effect = [[make_search_result(guid=f"guid-{i}")] for i in range(5)]
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 5
        for bid in book_ids:
            fresh = get_book(db_session, bid)
            assert fresh.status == BookStatus.GRABBED
            assert len(fresh.downloads) == 1

    def test_partial_failure_does_not_block_others(self, db_session):
        book1 = create_test_book(db_session, title="Good Book")
        book2 = create_test_book(db_session, title="Bad Book")
        db_session.commit()
        id1, id2 = book1.id, book2.id

        mock_search = MagicMock()
        mock_search.search_book.side_effect = [
            RuntimeError("search failed"),
            [make_search_result(guid="good-guid")],
        ]
        service = make_service(db_session, search_service=mock_search)

        grabbed = service.process_wanted_books()

        assert grabbed == 1
        statuses = {get_book(db_session, id1).status, get_book(db_session, id2).status}
        assert BookStatus.GRABBED in statuses
        assert BookStatus.FAILED in statuses
