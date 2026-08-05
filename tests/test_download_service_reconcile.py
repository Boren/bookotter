from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.clients.qbittorrent_client import QBittorrentClient, TorrentState
from backend.database import Base
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.download_service import DownloadService
from backend.utils.clock import naive_utcnow

REAL_HASH = "aabbccdd11223344aabbccdd11223344aabbccdd"
MAGNET_WITH_REAL_HASH = f"magnet:?xt=urn:btih:{REAL_HASH}&dn=TestBook"
MD5_JUNK_HASH = "801c5cd1bb38180a558b1907e27cf7b5"


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
    return mock


@pytest.fixture
def service(qbit, SessionLocal):
    return DownloadService(qbit_client=qbit, db_session_factory=SessionLocal, category="books")


@pytest.fixture
def book_record(db):
    book = Book(title="Test Book", hardcover_id="test-book", status=BookStatus.DOWNLOADING.value)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


class TestReconcileRepairLegacyHash:
    def test_repairs_md5_hash_when_qbit_has_real_hash(self, service, qbit, db, book_record):
        dl = Download(
            book_id=book_record.id,
            torrent_hash=MD5_JUNK_HASH,
            torrent_name="Test Book EPUB",
            indexer_name="TestIndexer",
            download_url=MAGNET_WITH_REAL_HASH,
            size=1024,
            seeders=5,
            status=DownloadStatus.DOWNLOADING.value,
            created_at=naive_utcnow() - timedelta(minutes=5),
        )
        db.add(dl)
        db.commit()

        qbit.get_torrents.return_value = [{"hash": REAL_HASH, "state": TorrentState.DOWNLOADING, "progress": 0.5}]
        service.reconcile_on_startup()

        db.refresh(dl)
        assert dl.torrent_hash == REAL_HASH
        assert dl.status == DownloadStatus.DOWNLOADING.value
        assert dl.error_message is None

    def test_genuine_miss_marks_failed(self, service, qbit, db, book_record):
        other_hash = "1234567890abcdef1234567890abcdef12345678"
        dl = Download(
            book_id=book_record.id,
            torrent_hash="deadbeef" * 5,
            torrent_name="Test Book EPUB",
            indexer_name="TestIndexer",
            download_url=f"magnet:?xt=urn:btih:{other_hash}&dn=TestBook",
            size=1024,
            seeders=5,
            status=DownloadStatus.DOWNLOADING.value,
            created_at=naive_utcnow() - timedelta(minutes=5),
        )
        db.add(dl)
        db.commit()

        qbit.get_torrents.return_value = []
        counts = service.reconcile_on_startup()

        db.refresh(dl)
        assert dl.status == DownloadStatus.FAILED.value
        assert "not found" in dl.error_message.lower()
        assert counts["failed"] == 1

    def test_grace_window_skips_fresh_download(self, service, qbit, db, book_record):
        dl = Download(
            book_id=book_record.id,
            torrent_hash=REAL_HASH,
            torrent_name="Test Book EPUB",
            indexer_name="TestIndexer",
            download_url=MAGNET_WITH_REAL_HASH,
            size=1024,
            seeders=5,
            status=DownloadStatus.QUEUED.value,
            created_at=naive_utcnow() - timedelta(seconds=5),
        )
        db.add(dl)
        db.commit()

        qbit.get_torrents.return_value = []
        counts = service.reconcile_on_startup()

        db.refresh(dl)
        assert dl.status != DownloadStatus.FAILED.value
        assert counts["failed"] == 0
