# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""Tests for Kindle delivery state machine: timeout, success, retry counter, auto-reconnect."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.models.book import BookStatus, KindleDeliveryStatus
from backend.services.pipeline_service import PipelineService
from tests.helpers import create_test_book


def _make_service(db_session) -> PipelineService:
    service = PipelineService(
        db_session_factory=lambda: db_session,
        search_service=MagicMock(),
    )
    service.db = db_session
    service.kindle_client = MagicMock()
    service._get_kindle_config = MagicMock(return_value={"hostname": "kindle"})
    return service


class TestKindleDeliveryTimeout:
    def test_timeout_transitions_to_skipped(self, db_session):
        """PENDING book older than 14 days transitions to SKIPPED."""
        book = create_test_book(db_session, status=BookStatus.IN_LIBRARY)
        book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
        book.kindle_first_pending_at = datetime.utcnow() - timedelta(days=15)
        db_session.commit()
        book_id = book.id

        service = _make_service(db_session)
        service.process_kindle_delivery_books()

        db_session.expire_all()
        refreshed = db_session.get(type(book), book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.SKIPPED.value

    def test_auto_retry_on_reconnect(self, db_session):
        """SKIPPED book transitions back to PENDING when Kindle becomes reachable."""
        book = create_test_book(db_session, status=BookStatus.IN_LIBRARY)
        book.kindle_delivery_status = KindleDeliveryStatus.SKIPPED.value
        db_session.commit()
        book_id = book.id

        service = _make_service(db_session)
        service.kindle_client._get_or_create_ssh.return_value = MagicMock()

        service.process_kindle_delivery_books()

        db_session.expire_all()
        refreshed = db_session.get(type(book), book_id)
        assert refreshed.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert refreshed.kindle_first_pending_at is not None
