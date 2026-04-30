"""Tests for RSS API routes — /api/rss/status and /api/rss/sync endpoints."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from backend.api.routes.rss import get_rss_status, trigger_rss_sync
from backend.models.rss import RssIndexerState


def _make_mock_rss_service(
    is_in_progress: bool = False,
    last_sync_started_at: str | None = None,
    last_sync_completed_at: str | None = None,
    recent_matches: list[dict[str, Any]] | None = None,
) -> Any:
    """Create a mock RssSyncService for testing."""
    service = MagicMock()
    service.is_sync_in_progress.return_value = is_in_progress
    service.run_sync_cycle = MagicMock()
    service._last_sync_started_at = last_sync_started_at
    service._last_sync_completed_at = last_sync_completed_at
    service._recent_matches = recent_matches or []
    return service


def _make_request(rss_service: Any = None) -> Any:
    """Create a mock Request object with app.state.rss_service."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(rss_service=rss_service)))


class TestGetRssStatus:
    """Tests for GET /api/rss/status endpoint."""

    def test_get_status_default(self, db_session):
        """Fresh DB; assert response shape and enabled reflects config."""
        mock_service = _make_mock_rss_service(is_in_progress=False)
        request = _make_request(rss_service=mock_service)

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": False}}

            response = asyncio.run(get_rss_status(request, db_session))
            data = json.loads(bytes(response.body))
            assert "enabled" in data
            assert data["enabled"] is False
            assert "syncInProgress" in data
            assert data["syncInProgress"] is False
            assert "lastSyncStartedAt" in data
            assert data["lastSyncStartedAt"] is None
            assert "lastSyncCompletedAt" in data
            assert data["lastSyncCompletedAt"] is None
            assert "indexers" in data
            assert isinstance(data["indexers"], list)
            assert "recentMatches" in data
            assert isinstance(data["recentMatches"], list)

    def test_get_status_with_indexers(self, db_session):
        """Pre-populate RssIndexerState rows; assert they appear in response."""
        indexer1 = RssIndexerState(
            indexer_id=1,
            indexer_name="Test Indexer 1",
            last_poll_at=datetime.now(UTC),
            last_status="ok",
            items_seen_count=10,
            items_grabbed_count=2,
        )
        indexer2 = RssIndexerState(
            indexer_id=2,
            indexer_name="Test Indexer 2",
            last_poll_at=datetime.now(UTC),
            last_status="error",
            last_error="Connection timeout",
            items_seen_count=5,
            items_grabbed_count=0,
        )
        db_session.add(indexer1)
        db_session.add(indexer2)
        db_session.commit()

        mock_service = _make_mock_rss_service(is_in_progress=False)
        request = _make_request(rss_service=mock_service)

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": True}}

            response = asyncio.run(get_rss_status(request, db_session))
            data = json.loads(bytes(response.body))
            assert data["enabled"] is True
            assert len(data["indexers"]) == 2

            idx1 = data["indexers"][0]
            assert idx1["indexerId"] == 1
            assert idx1["indexerName"] == "Test Indexer 1"
            assert idx1["lastStatus"] == "ok"
            assert idx1["itemsSeenCount"] == 10
            assert idx1["itemsGrabbedCount"] == 2

            idx2 = data["indexers"][1]
            assert idx2["indexerId"] == 2
            assert idx2["indexerName"] == "Test Indexer 2"
            assert idx2["lastStatus"] == "error"
            assert idx2["lastError"] == "Connection timeout"
            assert idx2["itemsSeenCount"] == 5
            assert idx2["itemsGrabbedCount"] == 0

    def test_get_status_includes_runtime_sync_metadata(self, db_session):
        """Runtime service state should flow through to status response."""
        mock_service = _make_mock_rss_service(
            last_sync_started_at="2026-04-30T10:00:00+00:00",
            last_sync_completed_at="2026-04-30T10:01:00+00:00",
            recent_matches=[
                {
                    "book_id": 42,
                    "guid": "rss-guid",
                    "indexer": "Test Indexer",
                    "title": "The Hobbit (EPUB)",
                    "matched_at": "2026-04-30T10:00:30+00:00",
                }
            ],
        )
        request = _make_request(rss_service=mock_service)

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": True}}

            response = asyncio.run(get_rss_status(request, db_session))
            data = json.loads(bytes(response.body))

        assert data["lastSyncStartedAt"] == "2026-04-30T10:00:00+00:00"
        assert data["lastSyncCompletedAt"] == "2026-04-30T10:01:00+00:00"
        assert data["recentMatches"][0]["guid"] == "rss-guid"


class TestPostRssSync:
    """Tests for POST /api/rss/sync endpoint."""

    def test_post_sync_starts_when_idle(self, db_session):
        """Assert 200 + {"status": "started"}, BackgroundTasks invoked."""
        from fastapi import BackgroundTasks

        mock_service = _make_mock_rss_service(is_in_progress=False)
        request = _make_request(rss_service=mock_service)
        background_tasks = BackgroundTasks()

        response = asyncio.run(trigger_rss_sync(request, background_tasks))
        data = json.loads(bytes(response.body))
        assert data["status"] == "started"
        assert len(background_tasks.tasks) > 0

    def test_post_sync_returns_409_when_in_progress(self, db_session):
        """Hold the sync lock; assert 409 + {"status": "in_progress"}."""
        from fastapi import BackgroundTasks

        mock_service = _make_mock_rss_service(is_in_progress=True)
        request = _make_request(rss_service=mock_service)
        background_tasks = BackgroundTasks()

        response = asyncio.run(trigger_rss_sync(request, background_tasks))
        data = json.loads(bytes(response.body))
        assert response.status_code == 409
        assert data["status"] == "in_progress"
        assert data["reason"] == "sync_in_progress"
        assert not mock_service.run_sync_cycle.called

    def test_post_sync_disabled(self, db_session):
        """Config has rss.enabled: false; assert 200 with {"status": "disabled"} OR 503."""
        from fastapi import BackgroundTasks

        mock_service = _make_mock_rss_service(is_in_progress=False)
        request = _make_request(rss_service=mock_service)
        background_tasks = BackgroundTasks()

        response = asyncio.run(trigger_rss_sync(request, background_tasks))
        data = json.loads(bytes(response.body))
        assert response.status_code == 200
        assert data["status"] == "started"
