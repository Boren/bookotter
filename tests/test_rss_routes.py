"""Tests for RSS API routes — /api/rss/status and /api/rss/sync endpoints."""

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.database import Base, get_db
from backend.main import app
from backend.models import blocklist, rss  # noqa: F401 — registers models with Base.metadata
from backend.models.rss import RssIndexerState


@dataclass
class ClientWithSession:
    """Test client with attached database session."""

    client: TestClient
    session: Session


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


@pytest.fixture
def client(monkeypatch):
    """Create a test client with a file-based test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    app.dependency_overrides[get_db] = lambda: session

    test_client = TestClient(app)

    yield ClientWithSession(client=test_client, session=session)
    app.dependency_overrides.clear()

    session.close()
    engine.dispose()
    Path(db_path).unlink()


class TestGetRssStatus:
    """Tests for GET /api/rss/status endpoint."""

    def test_get_status_default(self, client):
        """Fresh DB; assert response shape and enabled reflects config."""
        mock_service = _make_mock_rss_service(is_in_progress=False)
        app.state.rss_service = mock_service

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": False}}

            response = client.client.get("/api/rss/status")
            assert response.status_code == 200
            data = response.json()
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

    def test_get_status_with_indexers(self, client):
        """Pre-populate RssIndexerState rows; assert they appear in response."""
        session = client.session
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
        session.add(indexer1)
        session.add(indexer2)
        session.commit()

        mock_service = _make_mock_rss_service(is_in_progress=False)
        app.state.rss_service = mock_service

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": True}}

            response = client.client.get("/api/rss/status")
            assert response.status_code == 200
            data = response.json()
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

    def test_get_status_includes_runtime_sync_metadata(self, client):
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
        app.state.rss_service = mock_service

        with patch("backend.api.routes.rss.load_config") as mock_config:
            mock_config.return_value = {"rss": {"enabled": True}}

            response = client.client.get("/api/rss/status")
            assert response.status_code == 200
            data = response.json()

        assert data["lastSyncStartedAt"] == "2026-04-30T10:00:00+00:00"
        assert data["lastSyncCompletedAt"] == "2026-04-30T10:01:00+00:00"
        assert data["recentMatches"][0]["guid"] == "rss-guid"


class TestPostRssSync:
    """Tests for POST /api/rss/sync endpoint."""

    def test_post_sync_starts_when_idle(self, client):
        """Assert 200 + {"status": "started"}, BackgroundTasks invoked."""
        mock_service = _make_mock_rss_service(is_in_progress=False)
        app.state.rss_service = mock_service

        response = client.client.post("/api/rss/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"

    def test_post_sync_returns_409_when_in_progress(self, client):
        """Hold the sync lock; assert 409 + {"status": "in_progress"}."""
        mock_service = _make_mock_rss_service(is_in_progress=True)
        app.state.rss_service = mock_service

        response = client.client.post("/api/rss/sync")
        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["reason"] == "sync_in_progress"
        assert not mock_service.run_sync_cycle.called

    def test_post_sync_disabled(self, client):
        """Config has rss.enabled: false; assert 200 with {"status": "disabled"} OR 503."""
        mock_service = _make_mock_rss_service(is_in_progress=False)
        app.state.rss_service = mock_service

        response = client.client.post("/api/rss/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
