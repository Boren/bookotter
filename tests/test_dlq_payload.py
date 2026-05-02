"""Tests for DLQ payload including failure_history field."""

import asyncio

from backend.api.routes import library as library_routes
from backend.models.book import BookStatus
from tests.helpers import create_test_book


class TestDLQPayload:
    """Test that DLQ endpoint includes failure_history in responses."""

    def test_dlq_payload_includes_failure_history(self, db_session):
        """Verify DLQ response includes failure_history for permanent failures."""
        failure_history = [
            {
                "reason": "prowlarr_unreachable",
                "timestamp": "2026-01-01T00:00:00Z",
                "attempt": 1,
            }
        ]
        create_test_book(
            db_session,
            status=BookStatus.PERMANENT_FAILED.value,
            failure_history=failure_history,
        )
        db_session.commit()

        result = library_routes.get_dlq(db=db_session)

        assert "permanent_failed" in result
        assert "recent_failures" in result
        assert "counts" in result
        assert result["counts"]["permanent_failed"] == 1
        assert len(result["permanent_failed"]) == 1
        assert result["permanent_failed"][0]["failure_history"] == failure_history

    def test_dlq_payload_null_failure_history_preserved(self, db_session):
        """Verify NULL failure_history is preserved as None in JSON."""
        create_test_book(
            db_session,
            status=BookStatus.PERMANENT_FAILED.value,
            failure_history=None,
        )
        db_session.commit()

        result = library_routes.get_dlq(db=db_session)

        assert result["counts"]["permanent_failed"] == 1
        assert result["permanent_failed"][0]["failure_history"] is None

    def test_book_detail_includes_failure_history(self, db_session):
        """Verify book detail endpoint includes failure_history."""
        failure_history = [
            {
                "reason": "download_stalled",
                "timestamp": "2026-01-02T12:30:00Z",
                "attempt": 2,
            }
        ]
        book = create_test_book(
            db_session,
            status=BookStatus.PERMANENT_FAILED.value,
            failure_history=failure_history,
        )
        db_session.commit()

        result = asyncio.run(library_routes.get_book(book_id=book.id, db=db_session))

        assert "failure_history" in result
        assert result["failure_history"] == failure_history
