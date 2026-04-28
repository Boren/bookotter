# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.database import Base, backfill_missing_status
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from tests.helpers import create_test_book


class TestBackfillMissingStatus:
    def test_converts_idle_wanted_books_to_missing(self, monkeypatch):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        monkeypatch.setattr(database, "SessionLocal", SessionLocal)

        session = SessionLocal()
        book = create_test_book(session, title="Idle Wanted", status=BookStatus.WANTED, file_path=None)
        session.commit()

        assert backfill_missing_status() == 1
        assert backfill_missing_status() == 0

        refreshed = SessionLocal().get(Book, book.id)
        assert refreshed is not None
        assert refreshed.status == BookStatus.MISSING.value

        session.close()
        engine.dispose()

    def test_keeps_wanted_books_with_active_downloads(self, monkeypatch):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        monkeypatch.setattr(database, "SessionLocal", SessionLocal)

        session = SessionLocal()
        book = create_test_book(session, title="Active Wanted", status=BookStatus.WANTED, file_path=None)
        session.add(
            Download(
                book_id=book.id,
                torrent_hash="queued-hash",
                torrent_name="Active Wanted.epub",
                indexer_name="Indexer",
                download_url="https://example.com/queued",
                size=100,
                seeders=5,
                status=DownloadStatus.QUEUED.value,
            )
        )
        session.commit()

        assert backfill_missing_status() == 0

        refreshed = SessionLocal().get(Book, book.id)
        assert refreshed is not None
        assert refreshed.status == BookStatus.WANTED.value

        session.close()
        engine.dispose()
