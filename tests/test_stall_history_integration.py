"""Integration test: stall detection records failure_history via _append_failure_history."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.clients.qbittorrent_client import QBittorrentClient, TorrentState
from backend.database import Base
from backend.errors import FailureReason
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.download_service import DownloadService

HASH_HEX = "aabbccdd11223344aabbccdd11223344aabbccdd"
MAGNET_HEX = f"magnet:?xt=urn:btih:{HASH_HEX}&dn=TestBook"


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
    mock.get_torrents.return_value = []
    mock.delete_torrent.return_value = True
    return mock


@pytest.fixture
def service(qbit, SessionLocal):
    return DownloadService(qbit_client=qbit, db_session_factory=SessionLocal, category="test-books")


def _make_book(db, status=BookStatus.DOWNLOADING.value):
    """Create a test book with explicit timestamps (freezegun cannot patch column defaults)."""
    now = datetime.utcnow()
    book = Book(title="Stall Test Book", status=status, created_at=now, updated_at=now)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def _make_download(db, book_id, status=DownloadStatus.DOWNLOADING.value):
    """Create a test download record."""
    dl = Download(
        book_id=book_id,
        torrent_hash=HASH_HEX,
        torrent_name="Stall Test EPUB",
        indexer_name="TestIndexer",
        download_url=MAGNET_HEX,
        size=10_000,
        seeders=5,
        status=status,
        created_at=datetime.utcnow(),
    )
    db.add(dl)
    db.commit()
    db.refresh(dl)
    return dl


def _torrent_dict(downloaded: int, state: str = TorrentState.DOWNLOADING, progress: float = 0.5) -> dict:
    """Create a mock torrent dict from qBittorrent."""
    return {
        "hash": HASH_HEX,
        "state": state,
        "progress": progress,
        "downloaded": downloaded,
        "dlspeed": 1024,
        "eta": 60,
    }


class TestStallHistoryIntegration:
    """Verify that stall detection populates failure_history via _append_failure_history."""

    def test_stalled_book_has_failure_history_populated(self, service, qbit, db, SessionLocal):
        """Scenario 1: Stalled book has failure_history populated by existing stall path.

        - Seed a Book in DOWNLOADING state with no prior failure_history
        - Seed a Download with last_progress_at = now-31min, bytes_at_last_check = 2000
        - Use freeze_time to advance to 31min later (matching test_download_stall.py pattern)
        - Call service.monitor_downloads()
        - Reload book
        - Assert book.status == "failed"
        - Assert book.failure_reason == "download_stalled"
        - Assert len(book.failure_history) == 1
        - Assert book.failure_history[0]["reason"] == "download_stalled"
        - Assert book.failure_history[0]["attempt"] == 0
        """
        with freeze_time("2024-06-01 12:00:00") as frozen:
            # Create book in DOWNLOADING state with no failure_history
            book = _make_book(db, status=BookStatus.DOWNLOADING.value)
            book_id = book.id
            assert book.failure_history is None or len(book.failure_history) == 0

            # Create download with initial progress
            download = _make_download(db, book.id)
            download_id = download.id

            # First monitor call: record initial progress at 12:00:00
            qbit.get_torrents.return_value = [_torrent_dict(downloaded=2_000)]
            service.monitor_downloads()

            # Verify download is still DOWNLOADING
            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.status == DownloadStatus.DOWNLOADING.value
                assert dl.bytes_at_last_check == 2_000
                assert dl.last_progress_at is not None
            finally:
                verify.close()

            # Advance time by 31 minutes (triggers stall detection)
            frozen.move_to("2024-06-01 12:31:00")
            qbit.get_torrents.return_value = [_torrent_dict(downloaded=2_000)]  # No progress
            service.monitor_downloads()

            # Verify book is now FAILED with failure_history populated
            verify = SessionLocal()
            try:
                book_after = verify.query(Book).filter(Book.id == book_id).one()
                assert book_after.status == BookStatus.FAILED.value
                assert book_after.failure_reason == FailureReason.DOWNLOAD_STALLED.value
                assert book_after.failure_history is not None
                assert len(book_after.failure_history) == 1
                assert book_after.failure_history[0]["reason"] == FailureReason.DOWNLOAD_STALLED.value
                assert book_after.failure_history[0]["attempt"] == 0
                assert "timestamp" in book_after.failure_history[0]
            finally:
                verify.close()

            qbit.delete_torrent.assert_called_once_with(HASH_HEX)

    def test_existing_stall_tests_still_pass(self, service, qbit, db, SessionLocal):
        """Scenario 2: Existing stall tests still pass (regression check).

        Run the same test pattern as test_download_stall.py::test_31min_stall_fails_and_removes_torrent
        to ensure no regression.
        """
        with freeze_time("2024-06-01 12:00:00") as frozen:
            book = _make_book(db)
            download = _make_download(db, book.id)
            download_id = download.id
            book_id = book.id

            qbit.get_torrents.return_value = [_torrent_dict(downloaded=2_000)]
            service.monitor_downloads()

            frozen.move_to("2024-06-01 12:31:00")
            qbit.get_torrents.return_value = [_torrent_dict(downloaded=2_000)]
            service.monitor_downloads()

            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.status == DownloadStatus.FAILED.value
                assert dl.error_message is not None
                assert "Stalled" in dl.error_message

                book_after = verify.query(Book).filter(Book.id == book_id).one()
                assert book_after.status == BookStatus.FAILED.value
                assert book_after.failure_reason == FailureReason.DOWNLOAD_STALLED.value
            finally:
                verify.close()

            qbit.delete_torrent.assert_called_once_with(HASH_HEX)
