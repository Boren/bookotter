# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false

"""Tests for SEARCHING orphan reconciliation (Fix 3)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.models.book import BookStatus
from backend.services.download_service import reconcile_state
from tests.helpers import create_test_book


def _stale_book(db_session, *, age_seconds: int, **kwargs):
    book = create_test_book(db_session, status=BookStatus.SEARCHING.value, **kwargs)
    book.updated_at = datetime.utcnow() - timedelta(seconds=age_seconds)
    db_session.commit()
    return book


def _empty_qbit():
    mock = MagicMock()
    mock.get_torrents.return_value = []
    return mock


class TestSearchingOrphanReconcile:
    def test_stale_searching_recovered_to_wanted(self, db_session):
        book = _stale_book(db_session, age_seconds=600, title="Stale Book")

        result = reconcile_state(db_session, _empty_qbit())

        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert result["searching_orphans"] == 1

    def test_fresh_searching_left_alone(self, db_session):
        book = _stale_book(db_session, age_seconds=30, title="Fresh Book")

        result = reconcile_state(db_session, _empty_qbit())

        db_session.refresh(book)
        assert book.status == BookStatus.SEARCHING.value
        assert result["searching_orphans"] == 0

    def test_custom_grace_window_reconciles_at_threshold(self, db_session):
        book = _stale_book(db_session, age_seconds=90, title="Custom Grace")

        result = reconcile_state(db_session, _empty_qbit(), searching_grace_seconds=60)

        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert result["searching_orphans"] == 1

    def test_multiple_stale_searching_all_reconciled(self, db_session):
        books = [
            _stale_book(db_session, age_seconds=600, title=f"Stale {i}", isbn=f"978-0-{i:07d}-0") for i in range(3)
        ]

        result = reconcile_state(db_session, _empty_qbit())

        for book in books:
            db_session.refresh(book)
            assert book.status == BookStatus.WANTED.value
        assert result["searching_orphans"] == 3

    def test_clears_stale_failure_reason_on_recovery(self, db_session):
        book = create_test_book(db_session, status=BookStatus.SEARCHING.value, title="With Failure Reason")
        book.failure_reason = "stale_reason_from_previous_run"
        book.updated_at = datetime.utcnow() - timedelta(seconds=600)
        db_session.commit()

        reconcile_state(db_session, _empty_qbit())

        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert book.failure_reason is None

    def test_no_orphans_no_commit(self, db_session):
        create_test_book(db_session, status=BookStatus.IN_LIBRARY.value, title="Healthy Book")
        db_session.commit()

        result = reconcile_state(db_session, _empty_qbit())

        assert result == {
            "importing_orphans": 0,
            "downloading_orphans": 0,
            "searching_orphans": 0,
        }
