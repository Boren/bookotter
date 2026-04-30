from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.clients.qbittorrent_client import QBittorrentClient, TorrentState
from backend.database import Base
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.download_service import DownloadService
from backend.services.torrent_hash import extract_info_hash_from_url

MAGNET_HEX = "magnet:?xt=urn:btih:aabbccdd11223344aabbccdd11223344aabbccdd&dn=TestBook"
HASH_HEX = "aabbccdd11223344aabbccdd11223344aabbccdd"

MAGNET_B32 = "magnet:?xt=urn:btih:ABCDEFABCDEFABCDEFABCDEFABCDEFAB&dn=TestBook"

SEARCH_RESULT = {
    "title": "Test Book EPUB",
    "indexer": "TestIndexer",
    "size": 1024 * 1024,
    "seeders": 5,
    "download_url": "http://indexer.test/download/123",
    "magnet_url": MAGNET_HEX,
}


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def SessionLocal(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(SessionLocal):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def qbit():
    mock = MagicMock(spec=QBittorrentClient)
    mock.ensure_category_exists.return_value = True
    mock.add_torrent.return_value = True
    mock.get_torrent_files.return_value = []
    mock.get_torrents.return_value = []
    mock.set_file_priority.return_value = True
    mock.get_torrent_properties.return_value = None
    return mock


@pytest.fixture
def service(qbit, SessionLocal):
    return DownloadService(
        qbit_client=qbit,
        db_session_factory=SessionLocal,
        category="test-books",
    )


@pytest.fixture
def book_record(db):
    book = Book(title="Test Book", status=BookStatus.SEARCHING.value)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


@pytest.fixture
def queued_download(db, book_record):
    dl = Download(
        book_id=book_record.id,
        torrent_hash=HASH_HEX,
        torrent_name="Test Book EPUB",
        indexer_name="TestIndexer",
        download_url=MAGNET_HEX,
        size=1024,
        seeders=5,
        status=DownloadStatus.QUEUED.value,
    )
    db.add(dl)
    db.commit()
    db.refresh(dl)
    return dl


@pytest.fixture
def downloading_download(db, book_record):
    dl = Download(
        book_id=book_record.id,
        torrent_hash=HASH_HEX,
        torrent_name="Test Book EPUB",
        indexer_name="TestIndexer",
        download_url=MAGNET_HEX,
        size=1024,
        seeders=5,
        status=DownloadStatus.DOWNLOADING.value,
    )
    db.add(dl)
    db.commit()
    db.refresh(dl)
    return dl


class TestExtractHashFromMagnet:
    def test_hex_hash_returned_lowercase(self):
        result = extract_info_hash_from_url(MAGNET_HEX)
        assert result == HASH_HEX

    def test_hex_hash_uppercase_normalised(self):
        magnet = "magnet:?xt=urn:btih:AABBCCDD11223344AABBCCDD11223344AABBCCDD"
        assert extract_info_hash_from_url(magnet) == HASH_HEX

    def test_base32_hash_converted_to_hex(self):
        result = extract_info_hash_from_url(MAGNET_B32)
        assert result is not None
        assert len(result) == 40
        assert result.isalnum()

    def test_no_btih_returns_none(self):
        assert extract_info_hash_from_url("magnet:?dn=nobthihhere") is None

    def test_empty_string_returns_none(self):
        assert extract_info_hash_from_url("") is None

    def test_none_returns_none(self):
        assert extract_info_hash_from_url(None) is None  # type: ignore[arg-type]


class TestAddDownload:
    def test_happy_path_creates_download_record(self, service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            result = service.add_download(book_record.id, SEARCH_RESULT)

        assert result is not None
        assert result.torrent_hash == HASH_HEX
        assert result.torrent_name == "Test Book EPUB"
        assert result.indexer_name == "TestIndexer"
        assert result.status == DownloadStatus.QUEUED.value

    def test_happy_path_calls_add_torrent(self, service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            service.add_download(book_record.id, SEARCH_RESULT)

        qbit.add_torrent.assert_called_once_with(MAGNET_HEX, category="test-books")

    def test_happy_path_transitions_book_to_grabbed(self, service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            service.add_download(book_record.id, SEARCH_RESULT)

        db.refresh(book_record)
        assert book_record.status == BookStatus.GRABBED.value

    def test_no_url_returns_none(self, service):
        result = service.add_download(1, {"title": "X", "indexer": "Y", "size": 0, "seeders": 0})
        assert result is None

    def test_missing_magnet_url_returns_none(self, service):
        result = service.add_download(1, {**SEARCH_RESULT, "magnet_url": None, "download_url": None})
        assert result is None

    def test_no_magnet_url_returns_none(self, service):
        result = service.add_download(
            1,
            {**SEARCH_RESULT, "magnet_url": None, "download_url": "http://test/x.torrent"},
        )
        assert result is None

    def test_qbit_add_fails_returns_none(self, service, qbit, db, book_record):
        qbit.add_torrent.return_value = False
        with patch("backend.services.download_service.time.sleep"):
            result = service.add_download(book_record.id, SEARCH_RESULT)
        assert result is None

    def test_ensures_category_before_adding(self, service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            service.add_download(book_record.id, SEARCH_RESULT)
        qbit.ensure_category_exists.assert_called_once_with("test-books")


class TestMultiFileTorrentHandling:
    def test_single_file_no_priority_changes(self, service, qbit):
        qbit.get_torrent_files.return_value = [{"name": "book.epub"}]
        result = service._configure_file_priorities(HASH_HEX)
        qbit.set_file_priority.assert_not_called()
        assert result is None

    def test_empty_file_list_returns_none(self, service, qbit):
        qbit.get_torrent_files.return_value = []
        result = service._configure_file_priorities(HASH_HEX)
        assert result is None
        qbit.set_file_priority.assert_not_called()

    def test_multi_file_sets_priority_zero_on_non_epub(self, service, qbit):
        qbit.get_torrent_files.return_value = [
            {"name": "book.epub"},
            {"name": "cover.jpg"},
            {"name": "readme.txt"},
        ]
        service._configure_file_priorities(HASH_HEX)
        qbit.set_file_priority.assert_called_once_with(HASH_HEX, [1, 2], priority=0)

    def test_multi_file_returns_epub_name(self, service, qbit):
        qbit.get_torrent_files.return_value = [
            {"name": "subfolder/book.epub"},
            {"name": "cover.jpg"},
        ]
        result = service._configure_file_priorities(HASH_HEX)
        assert result == "subfolder/book.epub"

    def test_multi_file_no_epub_no_priority_change(self, service, qbit):
        qbit.get_torrent_files.return_value = [
            {"name": "book.mobi"},
            {"name": "cover.jpg"},
        ]
        result = service._configure_file_priorities(HASH_HEX)
        qbit.set_file_priority.assert_called_once_with(HASH_HEX, [0, 1], priority=0)
        assert result is None

    def test_add_download_sets_epub_file_path_from_multi_file(self, service, qbit, db, book_record):
        qbit.get_torrent_files.return_value = [
            {"name": "book.epub"},
            {"name": "cover.jpg"},
        ]
        with patch("backend.services.download_service.time.sleep"):
            result = service.add_download(book_record.id, SEARCH_RESULT)
        assert result is not None
        assert result.file_path == "book.epub"


class TestMonitorDownloads:
    def test_no_active_downloads_returns_zero(self, service):
        assert service.monitor_downloads() == 0

    def test_returns_count_of_processed_downloads(self, service, qbit, db, book_record, queued_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.QUEUED_DL, "progress": 0.0}]
        count = service.monitor_downloads()
        assert count == 1

    def test_queued_transitions_to_downloading_when_qbit_active(self, service, qbit, db, book_record, queued_download):
        book_record.status = BookStatus.GRABBED.value
        db.commit()
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.DOWNLOADING, "progress": 0.3}]
        service.monitor_downloads()

        db.refresh(queued_download)
        assert queued_download.status == DownloadStatus.DOWNLOADING.value

    def test_queued_to_downloading_updates_book_status(self, service, qbit, db, book_record, queued_download):
        book_record.status = BookStatus.GRABBED.value
        db.commit()
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.DOWNLOADING, "progress": 0.5}]
        service.monitor_downloads()

        db.refresh(book_record)
        assert book_record.status == BookStatus.DOWNLOADING.value

    def test_error_state_marks_download_failed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.ERROR, "progress": 0.0}]
        service.monitor_downloads()

        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.FAILED.value

    def test_missing_files_state_marks_failed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.MISSING_FILES, "progress": 0.0}]
        service.monitor_downloads()

        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.FAILED.value

    def test_completed_state_calls_handle_completed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.UPLOADING, "progress": 1.0}]
        epub_path = Path("/downloads/book.epub")
        qbit.get_completed_file_path.return_value = epub_path

        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        service.monitor_downloads()

        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.COMPLETED.value
        assert downloading_download.file_path == str(epub_path)

    def test_torrent_missing_from_qbit_does_not_crash(self, service, qbit, db, book_record, queued_download):
        qbit.get_torrents.return_value = []
        count = service.monitor_downloads()
        assert count == 1

        db.refresh(queued_download)
        assert queued_download.status == DownloadStatus.QUEUED.value

    def test_progress_one_triggers_completion(self, service, qbit, db, book_record, downloading_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.STALLED_UP, "progress": 1.0}]
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        service.monitor_downloads()

        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.COMPLETED.value


class TestHandleCompleted:
    def test_epub_found_marks_download_completed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        result = service.handle_completed(downloading_download)

        assert result is True
        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.COMPLETED.value

    def test_epub_found_sets_file_path(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        service.handle_completed(downloading_download)

        db.refresh(downloading_download)
        assert downloading_download.file_path == "/dl/book.epub"

    def test_epub_found_sets_completed_at(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        service.handle_completed(downloading_download)

        db.refresh(downloading_download)
        assert downloading_download.completed_at is not None

    def test_epub_found_transitions_book_to_importing(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        service.handle_completed(downloading_download)

        db.refresh(book_record)
        assert book_record.status == BookStatus.IMPORTING.value

    def test_no_epub_marks_download_failed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = None

        result = service.handle_completed(downloading_download)

        assert result is True
        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.FAILED.value

    def test_no_epub_sets_error_message(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = None

        service.handle_completed(downloading_download)

        db.refresh(downloading_download)
        assert downloading_download.error_message is not None
        assert "No EPUB" in downloading_download.error_message

    def test_returns_true_on_success(self, service, qbit, db, book_record, downloading_download):
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        assert service.handle_completed(downloading_download) is True


class TestReconcileOnStartup:
    def test_no_downloads_returns_zero_counts(self, service):
        counts = service.reconcile_on_startup()
        assert counts == {"reconciled": 0, "failed": 0, "completed": 0}

    def test_missing_torrent_marks_queued_as_failed(self, service, qbit, db, book_record, queued_download):
        queued_download.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()
        qbit.get_torrents.return_value = []

        counts = service.reconcile_on_startup()

        db.refresh(queued_download)
        assert queued_download.status == DownloadStatus.FAILED.value
        assert counts["failed"] == 1

    def test_missing_torrent_sets_error_message(self, service, qbit, db, book_record, queued_download):
        queued_download.created_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()
        qbit.get_torrents.return_value = []
        service.reconcile_on_startup()

        db.refresh(queued_download)
        assert "not found" in queued_download.error_message.lower()

    def test_completed_torrent_calls_handle_completed(self, service, qbit, db, book_record, downloading_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.UPLOADING, "progress": 1.0}]
        qbit.get_completed_file_path.return_value = Path("/dl/book.epub")
        book_record.status = BookStatus.DOWNLOADING.value
        db.commit()

        counts = service.reconcile_on_startup()

        db.refresh(downloading_download)
        assert downloading_download.status == DownloadStatus.COMPLETED.value
        assert counts["completed"] == 1

    def test_downloading_torrent_updates_queued_to_downloading(self, service, qbit, db, book_record, queued_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.DOWNLOADING, "progress": 0.4}]

        counts = service.reconcile_on_startup()

        db.refresh(queued_download)
        assert queued_download.status == DownloadStatus.DOWNLOADING.value
        assert counts["reconciled"] == 1

    def test_already_completed_with_missing_torrent_counts_reconciled(self, service, qbit, db, book_record):
        completed_dl = Download(
            book_id=book_record.id,
            torrent_hash=HASH_HEX,
            torrent_name="Test Book",
            indexer_name="TestIndexer",
            download_url=MAGNET_HEX,
            size=1024,
            seeders=5,
            status=DownloadStatus.COMPLETED.value,
        )
        db.add(completed_dl)
        db.commit()

        qbit.get_torrents.return_value = []

        counts = service.reconcile_on_startup()

        db.refresh(completed_dl)
        assert str(completed_dl.status) == DownloadStatus.COMPLETED.value
        assert counts["failed"] == 0
        assert counts["reconciled"] == 1

    def test_error_state_torrent_marked_failed(self, service, qbit, db, book_record, queued_download):
        qbit.get_torrents.return_value = [{"hash": HASH_HEX, "state": TorrentState.ERROR, "progress": 0.0}]

        counts = service.reconcile_on_startup()

        db.refresh(queued_download)
        assert queued_download.status == DownloadStatus.FAILED.value
        assert counts["failed"] == 1

    def test_terminal_downloads_not_returned(self, service, qbit, db, book_record):
        imported = Download(
            book_id=book_record.id,
            torrent_hash=HASH_HEX,
            torrent_name="Test Book",
            indexer_name="TestIndexer",
            download_url=MAGNET_HEX,
            size=1024,
            seeders=5,
            status=DownloadStatus.IMPORTED.value,
        )
        db.add(imported)
        db.commit()

        counts = service.reconcile_on_startup()
        assert counts == {"reconciled": 0, "failed": 0, "completed": 0}
        qbit.get_torrents.assert_not_called()
