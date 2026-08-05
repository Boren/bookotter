# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
"""Tests for auto-retry of FAILED books."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.constants import PIPELINE_AUTO_RETRY_ATTEMPTS, RETRY_BASE_DELAY
from backend.database import Base
from backend.errors import FailureReason
from backend.models.book import Book, BookStatus
from backend.services.pipeline_service import PipelineService
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    session.session_factory = Session
    yield session
    session.close()
    engine.dispose()


def make_service(db_session):
    return PipelineService(db_session_factory=db_session.session_factory, search_service=MagicMock())


def get_book(db_session, book_id):
    db_session.expire_all()
    return db_session.get(Book, book_id)


class TestAutoRetry:
    def test_failed_book_retried_after_cooldown(self, db_session):
        """FAILED book with retry_count=0 + cool-down passed → WANTED, retry_count=1."""
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.FAILED, updated_at=base_time)
        book.retry_count = 0
        book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        db_session.commit()
        book_id = book.id

        with freeze_time(base_time + timedelta(seconds=RETRY_BASE_DELAY + 1)):
            count = make_service(db_session).process_failed_books()

        book = get_book(db_session, book_id)
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 1
        assert book.failure_reason is None
        assert count == 1

    def test_failed_book_not_retried_within_cooldown(self, db_session):
        """FAILED book within cool-down window → NOT retried."""
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.FAILED, updated_at=base_time)
        book.retry_count = 0
        db_session.commit()
        book_id = book.id

        with freeze_time(base_time + timedelta(seconds=RETRY_BASE_DELAY - 0.5)):
            count = make_service(db_session).process_failed_books()

        book = get_book(db_session, book_id)
        assert book.status == BookStatus.FAILED.value
        assert book.retry_count == 0
        assert count == 0

    def test_budget_exhausted_to_permanent_failed(self, db_session):
        """FAILED book with retry_count==max → PERMANENT_FAILED."""
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.FAILED, updated_at=base_time)
        book.retry_count = PIPELINE_AUTO_RETRY_ATTEMPTS
        db_session.commit()
        book_id = book.id

        make_service(db_session).process_failed_books()

        book = get_book(db_session, book_id)
        assert book.status == BookStatus.PERMANENT_FAILED.value
        assert book.failure_reason == FailureReason.RETRY_BUDGET_EXHAUSTED.value

    def test_permanent_failed_not_picked_up(self, db_session):
        """PERMANENT_FAILED books NOT picked up by auto-retry."""
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.PERMANENT_FAILED, updated_at=base_time)
        book.retry_count = 0
        db_session.commit()
        book_id = book.id

        with freeze_time(base_time + timedelta(hours=1)):
            count = make_service(db_session).process_failed_books()

        book = get_book(db_session, book_id)
        assert book.status == BookStatus.PERMANENT_FAILED.value
        assert book.retry_count == 0
        assert count == 0

    def test_cooldown_is_exponential(self, db_session):
        """Cool-down sequence is exponential: 2s, 4s, 8s..."""
        base_time = naive_utcnow()
        book = create_test_book(db_session, status=BookStatus.FAILED, updated_at=base_time)
        book.retry_count = 2
        db_session.commit()
        book_id = book.id

        service = make_service(db_session)

        with freeze_time(base_time + timedelta(seconds=7)):
            count = service.process_failed_books()
        assert count == 0

        book = get_book(db_session, book_id)
        assert book.status == BookStatus.FAILED.value

        with freeze_time(base_time + timedelta(seconds=9)):
            count = service.process_failed_books()

        book = get_book(db_session, book_id)
        assert count == 1
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 3
