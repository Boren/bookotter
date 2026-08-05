"""Tests for POST /api/sync/kindle fail-fast behavior and concurrency guard."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.api.routes.sync as sync_routes
from backend.main import app

KINDLE_CONFIG = {
    "id": "abc123",
    "name": "My Kindle",
    "hostname": "kindle.local",
    "port": 22,
    "username": "root",
    "password": "",
    "ssh_key_path": "",
    "destination_path": "/mnt/us/books/",
}


@pytest.fixture
def client():
    yield TestClient(app)


@pytest.fixture(autouse=True)
def reset_sync_flag():
    sync_routes._kindle_sync_running = False
    yield
    sync_routes._kindle_sync_running = False


class TestTriggerKindleSync:
    def test_unknown_device_returns_404(self, client):
        with patch.object(sync_routes, "get_kindle_by_id", return_value=None):
            response = client.post("/api/sync/kindle", json={"kindle_device": "nope"})
        assert response.status_code == 404
        assert response.json()["detail"]["error"] == "kindle_not_found"

    def test_offline_kindle_returns_503_and_no_sync(self, client):
        background = MagicMock()
        with (
            patch.object(sync_routes, "get_kindle_by_id", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=False),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
        ):
            response = client.post("/api/sync/kindle", json={"kindle_device": "abc123"})

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["error"] == "kindle_offline"
        assert "My Kindle" in detail["message"]
        background.assert_not_called()
        # Guard flag must be released after the fail-fast path
        assert sync_routes._kindle_sync_running is False

    def test_reachable_kindle_starts_background_sync(self, client):
        background = MagicMock()
        with (
            patch.object(sync_routes, "get_kindle_by_id", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=True),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
            patch.object(sync_routes, "load_config", return_value={}),
        ):
            response = client.post("/api/sync/kindle", json={"kindle_device": "abc123"})

        assert response.status_code == 200
        assert response.json()["success"] is True
        background.assert_called_once_with(kindle_device="abc123")

    def test_dry_run_flag_returns_synchronous_report(self, client):
        report = {
            "transferred": 0,
            "skipped": 0,
            "failed": 0,
            "cleanup": None,
            "dry_run": True,
            "would_send": [{"book_id": 1, "title": "Dune", "remote_path": "/mnt/us/books/dune.epub"}],
            "would_delete": ["/mnt/us/books/orphan.epub"],
        }
        background = MagicMock(return_value=report)
        with (
            patch.object(sync_routes, "get_kindle_by_id", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=True),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
            patch.object(sync_routes, "load_config", return_value={}),
        ):
            response = client.post("/api/sync/kindle", json={"kindle_device": "abc123", "dry_run": True})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["dry_run"] is True
        assert body["would_send"][0]["title"] == "Dune"
        assert body["would_delete"] == ["/mnt/us/books/orphan.epub"]
        background.assert_called_once_with(kindle_device="abc123", dry_run=True)

    def test_config_dry_run_default_forces_dry_run(self, client):
        """transfer.dry_run=true in config turns every manual sync into a preview."""
        report = {
            "transferred": 0,
            "skipped": 0,
            "failed": 0,
            "cleanup": None,
            "dry_run": True,
            "would_send": [],
            "would_delete": [],
        }
        background = MagicMock(return_value=report)
        with (
            patch.object(sync_routes, "get_kindle_by_id", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=True),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
            patch.object(sync_routes, "load_config", return_value={"transfer": {"dry_run": True}}),
        ):
            response = client.post("/api/sync/kindle", json={"kindle_device": "abc123"})

        assert response.status_code == 200
        assert response.json()["dry_run"] is True
        background.assert_called_once_with(kindle_device="abc123", dry_run=True)

    def test_concurrent_sync_returns_409(self, client):
        sync_routes._kindle_sync_running = True
        with patch.object(sync_routes, "get_kindle_by_id", return_value=KINDLE_CONFIG):
            response = client.post("/api/sync/kindle", json={"kindle_device": "abc123"})
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "kindle_sync_already_running"

    def test_background_task_clears_flag_and_emits_failure(self):
        """The background task releases the guard flag and broadcasts kindle_sync_failed on error."""
        sync_routes._kindle_sync_running = True
        with (
            patch.object(sync_routes, "load_config", side_effect=RuntimeError("config exploded")),
            patch.object(sync_routes.ws_manager, "broadcast_sync") as broadcast,
        ):
            result = sync_routes._run_kindle_sync_background(kindle_device="abc123")

        assert "error" in result
        assert sync_routes._kindle_sync_running is False
        broadcast.assert_called_once()
        assert broadcast.call_args[0][0] == "kindle_sync_failed"

    def test_background_task_accepts_scheduler_kwargs(self):
        """The scheduler invokes with dry_run/trigger_type kwargs — must not TypeError."""
        with (
            patch.object(sync_routes, "load_config", side_effect=RuntimeError("stop early")),
            patch.object(sync_routes.ws_manager, "broadcast_sync"),
        ):
            result = sync_routes._run_kindle_sync_background(
                kindle_device="abc123", dry_run=False, trigger_type="scheduled"
            )
        assert "error" in result
