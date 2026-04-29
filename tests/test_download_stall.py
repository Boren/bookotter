"""Tests for download stall detection and hard timeout in DownloadService.monitor_downloads."""

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
    # SQLAlchemy column defaults capture function refs at class-definition time,
    # so freezegun cannot patch them here. Set timestamp fields explicitly.
    now = datetime.utcnow()
    book = Book(title="Stall Test Book", status=status, created_at=now, updated_at=now)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def _make_download(db, book_id, status=DownloadStatus.DOWNLOADING.value):
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
    return {
        "hash": HASH_HEX,
        "state": state,
        "progress": progress,
        "downloaded": downloaded,
        "dlspeed": 1024,
        "eta": 60,
    }


class TestDownloadStallDetection:
    def test_progress_resets_stall_clock(self, service, qbit, db, SessionLocal):
        with freeze_time("2024-06-01 12:00:00") as frozen:
            book = _make_book(db)
            download = _make_download(db, book.id)
            download_id = download.id

            qbit.get_torrents.return_value = [_torrent_dict(downloaded=1_000)]
            service.monitor_downloads()

            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.bytes_at_last_check == 1_000
                assert dl.last_progress_at is not None
                first_progress_at = dl.last_progress_at
                assert dl.status == DownloadStatus.DOWNLOADING.value
            finally:
                verify.close()

            frozen.move_to("2024-06-01 12:20:00")
            qbit.get_torrents.return_value = [_torrent_dict(downloaded=5_000)]
            service.monitor_downloads()

            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.status == DownloadStatus.DOWNLOADING.value
                assert dl.bytes_at_last_check == 5_000
                assert dl.last_progress_at > first_progress_at
                book_after = verify.query(Book).filter(Book.id == book.id).one()
                assert book_after.status == BookStatus.DOWNLOADING.value
                assert book_after.failure_reason is None
            finally:
                verify.close()

            qbit.delete_torrent.assert_not_called()

    def test_31min_stall_fails_and_removes_torrent(self, service, qbit, db, SessionLocal):
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

    def test_24h_hard_ceiling_fails_with_timeout(self, service, qbit, db, SessionLocal):
        with freeze_time("2024-06-01 00:00:00") as frozen:
            book = _make_book(db)
            download = _make_download(db, book.id)
            download_id = download.id
            book_id = book.id

            qbit.get_torrents.return_value = [_torrent_dict(downloaded=1_000)]
            service.monitor_downloads()

            # Advance 25h: even though we keep reporting fresh progress, the hard
            # ceiling must override and fail with DOWNLOAD_TIMEOUT (not STALLED).
            frozen.move_to("2024-06-02 01:00:00")
            qbit.get_torrents.return_value = [_torrent_dict(downloaded=9_500)]
            service.monitor_downloads()

            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.status == DownloadStatus.FAILED.value
                assert dl.error_message is not None
                assert "exceeded" in dl.error_message.lower()

                book_after = verify.query(Book).filter(Book.id == book_id).one()
                assert book_after.status == BookStatus.FAILED.value
                assert book_after.failure_reason == FailureReason.DOWNLOAD_TIMEOUT.value
            finally:
                verify.close()

            qbit.delete_torrent.assert_called_once_with(HASH_HEX)

    def test_completed_download_not_stalled(self, service, qbit, db, SessionLocal):
        with freeze_time("2024-06-01 12:00:00") as frozen:
            book = _make_book(db, status=BookStatus.IMPORTING.value)
            download = _make_download(db, book.id, status=DownloadStatus.COMPLETED.value)
            download_id = download.id

            frozen.move_to("2024-06-01 12:31:00")
            qbit.get_torrents.return_value = [
                _torrent_dict(
                    downloaded=download.size,
                    state=TorrentState.STALLED_UP,
                    progress=1.0,
                )
            ]
            count = service.monitor_downloads()

            assert count == 0
            verify = SessionLocal()
            try:
                dl = verify.query(Download).filter(Download.id == download_id).one()
                assert dl.status == DownloadStatus.COMPLETED.value
                book_after = verify.query(Book).filter(Book.id == book.id).one()
                assert book_after.status == BookStatus.IMPORTING.value
                assert book_after.failure_reason is None
            finally:
                verify.close()

            qbit.delete_torrent.assert_not_called()
