"""Tests for DLQ query helpers and endpoint."""

from backend.errors import FailureReason
from backend.models.book import BookStatus
from backend.services.dlq import get_failures_by_reason, get_permanent_failed, get_recent_failures
from tests.helpers import create_test_book


class TestDLQQueries:
    def test_permanent_failed_appears_in_get_permanent_failed(self, db_session):
        book = create_test_book(db_session, status=BookStatus.PERMANENT_FAILED.value)
        book.failure_reason = FailureReason.RETRY_BUDGET_EXHAUSTED.value
        db_session.commit()

        results = get_permanent_failed(db_session)
        assert any(b.id == book.id for b in results)

    def test_permanent_failed_not_in_recent_failures(self, db_session):
        book = create_test_book(db_session, status=BookStatus.PERMANENT_FAILED.value)
        db_session.commit()

        results = get_recent_failures(db_session)
        assert not any(b.id == book.id for b in results)

    def test_recent_failed_appears_in_recent_failures(self, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED.value)
        book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        db_session.commit()

        results = get_recent_failures(db_session)
        assert any(b.id == book.id for b in results)

    def test_filter_by_reason(self, db_session):
        book1 = create_test_book(db_session, title="Book 1", status=BookStatus.FAILED.value)
        book1.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        book2 = create_test_book(db_session, title="Book 2", status=BookStatus.FAILED.value)
        book2.failure_reason = FailureReason.QBIT_UNREACHABLE.value
        db_session.commit()

        stalled = get_failures_by_reason(db_session, FailureReason.DOWNLOAD_STALLED)
        assert any(b.id == book1.id for b in stalled)
        assert not any(b.id == book2.id for b in stalled)
