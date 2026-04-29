# pyright: reportGeneralTypeIssues=false
"""Tests for periodic reconciliation (reconcile_state)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.errors import FailureReason
from backend.models.book import BookStatus, Download, DownloadStatus
from backend.services.download_service import reconcile_state
from tests.helpers import create_test_book


class TestReconciliation:
    def test_orphan_importing_reconciled(self, db_session):
        """Book in IMPORTING with no COMPLETED download → FAILED after reconciliation."""
        book = create_test_book(db_session, status=BookStatus.IMPORTING.value)
        db_session.commit()

        mock_qbit = MagicMock()
        mock_qbit.get_torrents.return_value = []

        result = reconcile_state(db_session, mock_qbit)

        db_session.refresh(book)
        assert book.status == BookStatus.FAILED.value
        assert book.failure_reason == FailureReason.IMPORT_COPY_FAILED.value
        assert result["importing_orphans"] >= 1

    def test_orphan_downloading_reconciled(self, db_session):
        """Book in DOWNLOADING with no qBit torrent → FAILED after reconciliation."""
        book = create_test_book(db_session, status=BookStatus.DOWNLOADING.value)
        download = Download(
            book_id=book.id,
            torrent_hash="deadbeef" * 5,
            torrent_name="test",
            indexer_name="test",
            download_url="http://test",
            size=1024,
            seeders=1,
            status=DownloadStatus.DOWNLOADING.value,
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db_session.add(download)
        db_session.commit()

        mock_qbit = MagicMock()
        mock_qbit.get_torrents.return_value = []

        result = reconcile_state(db_session, mock_qbit)

        db_session.refresh(book)
        assert book.status == BookStatus.FAILED.value
        assert book.failure_reason == FailureReason.DOWNLOAD_TORRENT_ERROR.value
        assert result["downloading_orphans"] >= 1

    def test_reconciliation_idempotent(self, db_session):
        """Running reconciliation twice has same result as once."""
        create_test_book(db_session, status=BookStatus.IMPORTING.value)
        db_session.commit()

        mock_qbit = MagicMock()
        mock_qbit.get_torrents.return_value = []

        result1 = reconcile_state(db_session, mock_qbit)
        result2 = reconcile_state(db_session, mock_qbit)

        assert result1["importing_orphans"] >= 1
        assert result2["importing_orphans"] == 0
