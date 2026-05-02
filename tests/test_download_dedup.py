"""Tests for download deduplication, race-condition handling, and orphan torrent adoption."""

import threading
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.clients.qbittorrent_client import QBittorrentClient
from backend.database import Base
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.download_service import DownloadService
from backend.services.pipeline_service import PipelineService

HASH_A = "aabbccdd11223344aabbccdd11223344aabbccdd"
HASH_B = "ffeeddcc99887766ffeeddcc99887766ffeeddcc"
MAGNET_A = f"magnet:?xt=urn:btih:{HASH_A}&dn=Book+A"
MAGNET_B = f"magnet:?xt=urn:btih:{HASH_B}&dn=Book+B"

SEARCH_RESULT_A = {
    "title": "Book A.epub",
    "indexer": "TestIndexer",
    "size": 2048,
    "seeders": 10,
    "download_url": "http://indexer.test/a",
    "magnet_url": MAGNET_A,
}

SEARCH_RESULT_B = {
    "title": "Book B.epub",
    "indexer": "TestIndexer",
    "size": 2048,
    "seeders": 10,
    "download_url": "http://indexer.test/b",
    "magnet_url": MAGNET_B,
}


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
def file_engine(tmp_path):
    """File-based SQLite engine for concurrency tests where threads need real isolation."""
    db_path = tmp_path / "dedup_test.db"
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def file_SessionLocal(file_engine):
    return sessionmaker(bind=file_engine, autocommit=False, autoflush=False)


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
def download_service(qbit, SessionLocal):
    return DownloadService(
        qbit_client=qbit,
        db_session_factory=SessionLocal,
        category="test-books",
    )


@pytest.fixture
def book_record(db):
    book = Book(title="Dedup Test Book", hardcover_id="test-dedup-book", status=BookStatus.SEARCHING.value)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def make_search_result(magnet_url: str, title: str = "Book.epub") -> dict:
    return {
        "title": title,
        "indexer": "TestIndexer",
        "seeders": 10,
        "size": 5_000_000,
        "download_url": "https://example.com/torrent/1",
        "magnet_url": magnet_url,
    }


class TestDownloadServiceDedup:
    def test_sequential_grab_no_duplicate_row(self, download_service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            first = download_service.add_download(book_record.id, SEARCH_RESULT_A)
            second = download_service.add_download(book_record.id, SEARCH_RESULT_A)

        assert first is not None
        assert second is not None
        assert first.id == second.id

        rows = db.query(Download).filter(Download.book_id == book_record.id).all()
        assert len(rows) == 1

    def test_sequential_grab_calls_qbit_add_once(self, download_service, qbit, db, book_record):
        with patch("backend.services.download_service.time.sleep"):
            download_service.add_download(book_record.id, SEARCH_RESULT_A)
            download_service.add_download(book_record.id, SEARCH_RESULT_A)

        assert qbit.add_torrent.call_count == 1

    def test_dedup_skips_when_existing_downloading(self, download_service, qbit, db, book_record):
        existing = Download(
            book_id=book_record.id,
            torrent_hash=HASH_A,
            torrent_name="already here",
            indexer_name="X",
            download_url=MAGNET_A,
            size=1,
            seeders=1,
            status=DownloadStatus.DOWNLOADING.value,
        )
        db.add(existing)
        db.commit()

        with patch("backend.services.download_service.time.sleep"):
            result = download_service.add_download(book_record.id, SEARCH_RESULT_A)

        assert result is not None
        assert result.id == existing.id
        qbit.add_torrent.assert_not_called()

    def test_dedup_by_hash_across_books(self, download_service, qbit, db):
        book_one = Book(title="Book One", hardcover_id="test-book-one", status=BookStatus.SEARCHING.value)
        book_two = Book(title="Book Two", hardcover_id="test-book-two", status=BookStatus.SEARCHING.value)
        db.add_all([book_one, book_two])
        db.commit()

        with patch("backend.services.download_service.time.sleep"):
            first = download_service.add_download(book_one.id, SEARCH_RESULT_A)
            second = download_service.add_download(book_two.id, SEARCH_RESULT_A)

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert qbit.add_torrent.call_count == 1


class TestOrphanAdoption:
    def test_orphan_torrent_in_qbit_is_adopted(self, download_service, qbit, db, book_record):
        qbit.get_torrent_properties.return_value = {
            "hash": HASH_A,
            "name": "Orphan",
            "size": 1024,
        }

        with patch("backend.services.download_service.time.sleep"):
            result = download_service.add_download(book_record.id, SEARCH_RESULT_A)

        assert result is not None
        assert result.torrent_hash == HASH_A
        qbit.add_torrent.assert_not_called()

    def test_orphan_creates_download_row(self, download_service, qbit, db, book_record):
        qbit.get_torrent_properties.return_value = {"hash": HASH_A}

        with patch("backend.services.download_service.time.sleep"):
            download_service.add_download(book_record.id, SEARCH_RESULT_A)

        rows = db.query(Download).filter(Download.book_id == book_record.id).all()
        assert len(rows) == 1
        assert rows[0].torrent_hash == HASH_A
        assert rows[0].status == DownloadStatus.QUEUED.value

    def test_non_orphan_takes_normal_add_path(self, download_service, qbit, db, book_record):
        qbit.get_torrent_properties.return_value = None

        with patch("backend.services.download_service.time.sleep"):
            download_service.add_download(book_record.id, SEARCH_RESULT_A)

        qbit.add_torrent.assert_called_once_with(MAGNET_A, category="test-books")


class TestIntegrityErrorRace:
    def test_unique_violation_adopts_existing(self, download_service, qbit, db, book_record):
        existing = Download(
            book_id=book_record.id,
            torrent_hash=HASH_A,
            torrent_name="raced",
            indexer_name="X",
            download_url=MAGNET_A,
            size=1,
            seeders=1,
            status=DownloadStatus.QUEUED.value,
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id

        with patch("backend.services.download_service.time.sleep"):
            result = download_service.add_download(book_record.id, SEARCH_RESULT_A)

        assert result is not None
        assert result.id == existing_id

        rows = db.query(Download).filter(Download.torrent_hash == HASH_A).all()
        assert len(rows) == 1


class TestConcurrentGrabs:
    def test_concurrent_add_download_no_duplicates(self, file_SessionLocal, qbit):
        setup_db = file_SessionLocal()
        book = Book(title="Concurrent Book", hardcover_id="test-concurrent-book", status=BookStatus.SEARCHING.value)
        setup_db.add(book)
        setup_db.commit()
        book_id = book.id
        setup_db.close()

        service = DownloadService(
            qbit_client=qbit,
            db_session_factory=file_SessionLocal,
            category="test-books",
        )

        barrier = threading.Barrier(5)
        results: list = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            with patch("backend.services.download_service.time.sleep"):
                res = service.add_download(book_id, SEARCH_RESULT_A)
            with results_lock:
                results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify_db = file_SessionLocal()
        try:
            rows = verify_db.query(Download).filter(Download.book_id == book_id).all()
            assert len(rows) == 1, f"Expected 1 Download row, got {len(rows)}"
        finally:
            verify_db.close()


class TestPipelineServiceDedup:
    def test_pipeline_skips_when_active_download_exists(self, db, SessionLocal, book_record):
        existing = Download(
            book_id=book_record.id,
            torrent_hash=HASH_A,
            torrent_name="already there",
            indexer_name="X",
            download_url=MAGNET_A,
            size=1,
            seeders=1,
            status=DownloadStatus.QUEUED.value,
        )
        db.add(existing)
        book_record.status = BookStatus.WANTED.value
        db.commit()

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(MAGNET_B)]

        def factory():
            return SessionLocal()

        service = PipelineService(
            search_service=mock_search,
            db_session_factory=factory,
        )

        grabbed = service.process_wanted_books()
        assert grabbed == 0

        verify = SessionLocal()
        try:
            rows = verify.query(Download).filter(Download.book_id == book_record.id).all()
            assert len(rows) == 1
            assert rows[0].id == existing.id
        finally:
            verify.close()

    def test_pipeline_concurrent_grab_no_duplicate(self, file_SessionLocal):
        setup_db = file_SessionLocal()
        book = Book(title="Pipeline Concurrent", hardcover_id="test-pipeline-concurrent", status=BookStatus.WANTED.value)
        setup_db.add(book)
        setup_db.commit()
        book_id = book.id
        setup_db.close()

        barrier = threading.Barrier(3)
        grabbed_counts: list = []
        counts_lock = threading.Lock()

        def factory():
            return file_SessionLocal()

        def worker():
            mock_search = MagicMock()
            mock_search.search_book.return_value = [make_search_result(MAGNET_A)]
            service = PipelineService(
                search_service=mock_search,
                db_session_factory=factory,
            )
            barrier.wait()
            n = service.process_wanted_books()
            with counts_lock:
                grabbed_counts.append(n)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        verify = file_SessionLocal()
        try:
            rows = verify.query(Download).filter(Download.book_id == book_id).all()
            assert len(rows) == 1, f"Expected 1 Download row, got {len(rows)}"
        finally:
            verify.close()
