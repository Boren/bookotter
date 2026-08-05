"""Tests for GET /api/kindles/{id}/status (cached reachability probe)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.api.routes.kindles as kindles_routes
from backend.main import app


@pytest.fixture
def client():
    kindles_routes._status_cache.clear()
    yield TestClient(app)
    kindles_routes._status_cache.clear()


def _kindle_config(hostname="kindle.local"):
    return {
        "id": "abc12345",
        "name": "Test Kindle",
        "hostname": hostname,
        "port": 22,
        "username": "root",
        "password": "",
        "ssh_key_path": "",
        "destination_path": "/mnt/us/books/",
    }


class TestKindleStatusRoute:
    def test_unknown_kindle_404(self, client):
        with patch.object(kindles_routes, "get_kindle_by_id", return_value=None):
            response = client.get("/api/kindles/nope/status")
        assert response.status_code == 404

    def test_unconfigured_hostname(self, client):
        with patch.object(kindles_routes, "get_kindle_by_id", return_value=_kindle_config(hostname="")):
            response = client.get("/api/kindles/abc12345/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["reachable"] is False
        assert data["checked_at"] is None

    @pytest.mark.parametrize("reachable", [True, False])
    def test_probe_result_returned(self, client, reachable):
        with (
            patch.object(kindles_routes, "get_kindle_by_id", return_value=_kindle_config()),
            patch.object(kindles_routes.KindleClient, "is_reachable", return_value=reachable),
        ):
            response = client.get("/api/kindles/abc12345/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is True
        assert data["reachable"] is reachable
        assert data["checked_at"] is not None
        assert data["cached"] is False

    def test_cache_hit_within_ttl(self, client):
        probe_calls = []

        def fake_probe(self, timeout=None):
            probe_calls.append(1)
            return True

        with (
            patch.object(kindles_routes, "get_kindle_by_id", return_value=_kindle_config()),
            patch.object(kindles_routes.KindleClient, "is_reachable", fake_probe),
        ):
            first = client.get("/api/kindles/abc12345/status")
            second = client.get("/api/kindles/abc12345/status")

        assert first.json()["cached"] is False
        assert second.json()["cached"] is True
        assert len(probe_calls) == 1

    def test_refresh_bypasses_cache(self, client):
        probe_calls = []

        def fake_probe(self, timeout=None):
            probe_calls.append(1)
            return True

        with (
            patch.object(kindles_routes, "get_kindle_by_id", return_value=_kindle_config()),
            patch.object(kindles_routes.KindleClient, "is_reachable", fake_probe),
        ):
            client.get("/api/kindles/abc12345/status")
            refreshed = client.get("/api/kindles/abc12345/status?refresh=true")

        assert refreshed.json()["cached"] is False
        assert len(probe_calls) == 2
