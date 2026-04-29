"""Tests for CLI force-retry subcommand."""

from backend.cli import force_retry_book
from backend.errors import FailureReason
from backend.models.book import BookStatus
from tests.helpers import create_test_book


class TestCliForceRetry:
    def test_force_retry_failed_book_exits_0(self, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED)
        book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        db_session.commit()
        book_id = book.id

        exit_code = force_retry_book(book_id, db_session)

        assert exit_code == 0
        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 0
        assert book.failure_reason is None
        assert book.low_confidence is False

    def test_force_retry_nonexistent_book_exits_1(self, db_session):
        exit_code = force_retry_book(99999, db_session)
        assert exit_code == 1

    def test_force_retry_in_library_book_exits_2(self, db_session):
        book = create_test_book(db_session, status=BookStatus.IN_LIBRARY)
        db_session.commit()

        exit_code = force_retry_book(book.id, db_session)
        assert exit_code == 2

    def test_force_retry_permanent_failed_exits_0(self, db_session):
        book = create_test_book(db_session, status=BookStatus.PERMANENT_FAILED)
        book.failure_reason = FailureReason.RETRY_BUDGET_EXHAUSTED.value
        db_session.commit()

        exit_code = force_retry_book(book.id, db_session)

        assert exit_code == 0
        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 0
        assert book.failure_reason is None
