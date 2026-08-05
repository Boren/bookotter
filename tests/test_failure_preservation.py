# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""Tests for failure_history preservation across retries (T11)."""

import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.constants import RETRY_BASE_DELAY
from backend.database import Base, get_db
from backend.errors import FailureReason
from backend.main import app
from backend.models import blocklist  # noqa: F401 - register tables
from backend.models.book import Book, BookStatus
from backend.services.pipeline_service import PipelineService
from backend.utils.clock import naive_utcnow
from backend.utils.failure import FAILURE_HISTORY_MAX, _append_failure_history
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    session.session_factory = SessionLocal
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def shared_db_factory():
    """File-based SQLite session factory shared across threads."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(bind=engine)
        SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        yield SessionFactory
        engine.dispose()


def make_service(db_session):
    return PipelineService(db_session_factory=db_session.session_factory, search_service=MagicMock())


def get_book(db_session, book_id):
    db_session.expire_all()
    return db_session.get(Book, book_id)


class TestAutoRetryAppendsHistory:
    def test_auto_retry_appends_to_history_and_clears_reason(self, db_session):
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.FAILED.value, updated_at=base_time)
        book.retry_count = 1
        book.failure_reason = FailureReason.PROWLARR_UNREACHABLE.value
        db_session.commit()
        book_id = book.id

        with freeze_time(base_time + timedelta(seconds=RETRY_BASE_DELAY * 2 + 1)):
            count = make_service(db_session).process_failed_books()

        assert count == 1
        book = get_book(db_session, book_id)
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 2
        assert book.failure_reason is None
        assert book.failure_history is not None
        assert len(book.failure_history) == 1
        entry = book.failure_history[0]
        assert entry["reason"] == FailureReason.PROWLARR_UNREACHABLE.value
        assert entry["attempt"] == 1
        assert "timestamp" in entry
        assert "T" in entry["timestamp"]


class TestRingBufferCap:
    def test_ring_buffer_caps_at_five_entries(self, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED.value)
        db_session.commit()

        for i in range(6):
            book.retry_count = i
            _append_failure_history(book, f"reason_{i}")

        assert book.failure_history is not None
        assert len(book.failure_history) == FAILURE_HISTORY_MAX
        assert len(book.failure_history) == 5
        reasons = [e["reason"] for e in book.failure_history]
        assert reasons == ["reason_1", "reason_2", "reason_3", "reason_4", "reason_5"]
        assert "reason_0" not in reasons


class TestManualRetryRecordsSentinel:
    def test_manual_retry_appends_old_reason_then_manual_retry_marker(self, client, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED.value)
        book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        book.retry_count = 1
        db_session.commit()
        book_id = book.id

        response = client.post(f"/api/library/books/{book_id}/retry")

        assert response.status_code == 202
        book = get_book(db_session, book_id)
        assert book.status == BookStatus.WANTED.value
        assert book.failure_reason is None
        assert book.retry_count == 0
        assert book.failure_history is not None
        assert len(book.failure_history) == 2
        assert book.failure_history[0]["reason"] == FailureReason.DOWNLOAD_STALLED.value
        assert book.failure_history[0]["attempt"] == 1
        assert book.failure_history[1]["reason"] == "MANUAL_RETRY"
        assert book.failure_history[1]["attempt"] == 1


class TestConcurrentNoDoubleAppend:
    def test_concurrent_appends_do_not_produce_duplicate_entries(self, shared_db_factory):
        seed_db = shared_db_factory()
        try:
            book = create_test_book(seed_db, status=BookStatus.FAILED.value)
            book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
            seed_db.commit()
            book_id = book.id
        finally:
            seed_db.close()

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def append_in_thread(reason: str):
            db = shared_db_factory()
            try:
                barrier.wait()
                book = db.get(Book, book_id)
                _append_failure_history(book, reason)
                db.commit()
            except Exception as e:
                errors.append(e)
            finally:
                db.close()

        t1 = threading.Thread(target=append_in_thread, args=("reason_a",))
        t2 = threading.Thread(target=append_in_thread, args=("reason_b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Threads raised exceptions: {errors}"

        check_db = shared_db_factory()
        try:
            book = check_db.get(Book, book_id)
            history = list(book.failure_history or [])
            reasons = [e["reason"] for e in history]
            assert reasons.count("reason_a") <= 1, f"reason_a appended multiple times: {reasons}"
            assert reasons.count("reason_b") <= 1, f"reason_b appended multiple times: {reasons}"
            assert len(history) <= 2, f"More than 2 entries from 2 threads: {history}"
            assert len(history) >= 1, f"All concurrent appends were lost: {history}"
        finally:
            check_db.close()
