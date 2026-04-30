# pyright: reportGeneralTypeIssues=false

import tempfile
import threading
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_service import PipelineService
from backend.services.pipeline_states import can_transition, transition_book, transition_download
from tests.helpers import create_test_book


class TestMissingStateTransitions:
    def test_missing_to_searching(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.SEARCHING.value, db_session) is True
        assert book.status == BookStatus.SEARCHING.value

    def test_missing_to_failed(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.FAILED.value, db_session) is True
        assert book.status == BookStatus.FAILED.value

    def test_wanted_to_missing(self, db_session):
        assert can_transition(BookStatus.WANTED.value, BookStatus.MISSING.value) is True

    def test_failed_to_missing(self, db_session):
        assert can_transition(BookStatus.FAILED.value, BookStatus.MISSING.value) is True

    def test_missing_cannot_go_to_in_library(self, db_session):
        assert can_transition(BookStatus.MISSING.value, BookStatus.IN_LIBRARY.value) is False


class TestPermanentFailedTransitions:
    def test_permanent_failed_only_from_failed(self, db_session):
        """PERMANENT_FAILED can only be reached from FAILED."""
        # WANTED → PERMANENT_FAILED must be invalid
        assert can_transition(BookStatus.WANTED.value, BookStatus.PERMANENT_FAILED.value) is False
        # SEARCHING → PERMANENT_FAILED must be invalid
        assert can_transition(BookStatus.SEARCHING.value, BookStatus.PERMANENT_FAILED.value) is False
        # FAILED → PERMANENT_FAILED must be valid
        assert can_transition(BookStatus.FAILED.value, BookStatus.PERMANENT_FAILED.value) is True

    def test_permanent_failed_to_wanted_only(self, db_session):
        """PERMANENT_FAILED can only transition to WANTED (force-retry)."""
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.WANTED.value) is True
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.SEARCHING.value) is False
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.MISSING.value) is False
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.FAILED.value) is False

    def test_permanent_failed_transition_book(self, db_session):
        """transition_book correctly moves FAILED → PERMANENT_FAILED."""
        book = create_test_book(db_session, status=BookStatus.FAILED)
        assert transition_book(book, BookStatus.PERMANENT_FAILED.value, db_session) is True
        assert book.status == BookStatus.PERMANENT_FAILED.value

    def test_transition_book_returns_false_after_concurrent_status_change(self, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED)
        mock_result = MagicMock(rowcount=0)
        db_session.execute = MagicMock(return_value=mock_result)

        assert transition_book(book, BookStatus.PERMANENT_FAILED.value, db_session) is False
        assert book.status == BookStatus.FAILED.value


class TestPipelinePicksUpMissing:
    def test_process_wanted_books_includes_missing(self, db_session):
        wanted = create_test_book(db_session, title="Wanted Book", author_name="Author One", status=BookStatus.WANTED)
        missing = create_test_book(
            db_session, title="Missing Book", author_name="Author Two", status=BookStatus.MISSING
        )
        db_session.commit()
        wanted_id = wanted.id
        missing_id = missing.id

        search_service = MagicMock()
        search_service.search_book.side_effect = [
            [
                {
                    "guid": "wanted-guid",
                    "title": "Wanted.epub",
                    "indexer": "TestIndexer",
                    "seeders": 10,
                    "size": 1024,
                    "download_url": "https://example.com/wanted",
                    "magnet_url": "magnet:?xt=urn:btih:aaaaaaaaaa1111111111aaaaaaaaaa1111111111&dn=Wanted",
                }
            ],
            [
                {
                    "guid": "missing-guid",
                    "title": "Missing.epub",
                    "indexer": "TestIndexer",
                    "seeders": 12,
                    "size": 2048,
                    "download_url": "https://example.com/missing",
                    "magnet_url": "magnet:?xt=urn:btih:bbbbbbbbbb2222222222bbbbbbbbbb2222222222&dn=Missing",
                }
            ],
        ]

        service = PipelineService(search_service=search_service, db_session_factory=lambda: db_session)

        assert service.process_wanted_books() == 2

        db_session.expire_all()
        assert db_session.get(Book, wanted_id).status == BookStatus.GRABBED
        assert db_session.get(Book, missing_id).status == BookStatus.GRABBED


class TestAtomicTransitionsConcurrency:
    """Test atomic CAS (Compare-And-Swap) behavior under concurrent access."""

    def _create_file_db_session(self, db_path: str):
        """Create a new session connected to a file-based SQLite database."""
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()

    def test_transition_book_atomic_under_threads(self):
        """Two threads attempt WANTED→SEARCHING concurrently; exactly one returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_transitions.db")

            # Setup: create book in shared DB
            session = self._create_file_db_session(db_path)
            book = create_test_book(session, status=BookStatus.WANTED)
            book_id = book.id
            session.commit()
            session.close()

            # Synchronization barrier for deterministic timing
            barrier = Barrier(2)
            results = {}

            def thread_transition(thread_id: int):
                """Each thread gets its own session and attempts the same transition."""
                session = self._create_file_db_session(db_path)
                try:
                    book = session.get(Book, book_id)
                    assert book is not None
                    assert book.status == BookStatus.WANTED.value

                    # Synchronize both threads to hit UPDATE at the same time
                    barrier.wait()

                    # Attempt transition
                    result = transition_book(book, BookStatus.SEARCHING.value, session)
                    session.commit()
                    results[thread_id] = result
                finally:
                    session.close()

            # Run both threads
            t1 = threading.Thread(target=thread_transition, args=(1,))
            t2 = threading.Thread(target=thread_transition, args=(2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Verify: exactly one thread succeeded
            assert sum(results.values()) == 1, f"Expected exactly 1 True, got {sum(results.values())}"
            assert results[1] != results[2], "One thread should succeed, one should fail"

            # Verify final state
            session = self._create_file_db_session(db_path)
            final_book = session.get(Book, book_id)
            assert final_book.status == BookStatus.SEARCHING.value
            session.close()

    def test_transition_book_returns_false_on_invalid(self):
        """Terminal state (IN_LIBRARY) → WANTED is rejected without DB write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_invalid.db")
            session = self._create_file_db_session(db_path)

            book = create_test_book(session, status=BookStatus.IN_LIBRARY)
            session.commit()

            # Attempt invalid transition
            result = transition_book(book, BookStatus.WANTED.value, session)

            # Should return False without modifying DB
            assert result is False
            assert book.status == BookStatus.IN_LIBRARY.value

            session.close()

    def test_transition_book_returns_false_on_concurrent_change(self):
        """Thread A reads book, Thread B transitions it, then Thread A tries same transition → Thread A gets False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_concurrent_change.db")

            # Setup: create book
            session = self._create_file_db_session(db_path)
            book = create_test_book(session, status=BookStatus.WANTED)
            book_id = book.id
            session.commit()
            session.close()

            barrier_read = Barrier(2)
            barrier_transition = Barrier(2)
            results = {}

            def thread_a():
                """Thread A: read book, wait, then try transition."""
                session = self._create_file_db_session(db_path)
                try:
                    book = session.get(Book, book_id)
                    assert book.status == BookStatus.WANTED.value

                    # Signal that we've read the book
                    barrier_read.wait()

                    # Wait for Thread B to transition
                    barrier_transition.wait()

                    # By now, Thread B has already transitioned the book
                    # Try the same transition — should fail because status changed
                    result = transition_book(book, BookStatus.SEARCHING.value, session)
                    session.commit()
                    results["a"] = result
                finally:
                    session.close()

            def thread_b():
                """Thread B: wait for A to read, then transition."""
                barrier_read.wait()

                # Now transition the book
                session = self._create_file_db_session(db_path)
                try:
                    book = session.get(Book, book_id)
                    result = transition_book(book, BookStatus.SEARCHING.value, session)
                    session.commit()
                    results["b"] = result
                finally:
                    session.close()

                # Signal that transition is done
                barrier_transition.wait()

            t_a = threading.Thread(target=thread_a)
            t_b = threading.Thread(target=thread_b)
            t_a.start()
            t_b.start()
            t_a.join()
            t_b.join()

            # Thread B should succeed, Thread A should fail
            assert results["b"] is True, "Thread B should succeed"
            assert results["a"] is False, "Thread A should fail (status already changed)"

    def test_transition_download_atomic(self):
        """Same concurrent-transition pattern for downloads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_download_atomic.db")

            # Setup: create download
            session = self._create_file_db_session(db_path)
            download = Download(
                book_id=1,
                torrent_hash="abc123def456",
                torrent_name="Test.Download.epub",
                indexer_name="TestIndexer",
                download_url="https://example.com/test",
                size=1024000,
                seeders=5,
                status=DownloadStatus.QUEUED.value,
            )
            session.add(download)
            session.commit()
            download_id = download.id
            session.close()

            barrier = Barrier(2)
            results = {}

            def thread_transition(thread_id: int):
                """Each thread attempts QUEUED→DOWNLOADING concurrently."""
                session = self._create_file_db_session(db_path)
                try:
                    download = session.get(Download, download_id)
                    assert download is not None
                    assert download.status == DownloadStatus.QUEUED.value

                    barrier.wait()

                    result = transition_download(download, DownloadStatus.DOWNLOADING.value, session)
                    session.commit()
                    results[thread_id] = result
                finally:
                    session.close()

            t1 = threading.Thread(target=thread_transition, args=(1,))
            t2 = threading.Thread(target=thread_transition, args=(2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Exactly one should succeed
            assert sum(results.values()) == 1, f"Expected exactly 1 True, got {sum(results.values())}"

            # Verify final state
            session = self._create_file_db_session(db_path)
            final_download = session.get(Download, download_id)
            assert final_download.status == DownloadStatus.DOWNLOADING.value
            session.close()
