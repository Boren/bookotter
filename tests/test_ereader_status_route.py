"""Tests for GET /api/ereaders/{id}/status (cached reachability probe)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.api.routes.ereaders as ereaders_routes
from backend.main import app


@pytest.fixture
def client():
    ereaders_routes._status_cache.clear()
    yield TestClient(app)
    ereaders_routes._status_cache.clear()


def _ereader_config(hostname="ereader.local"):
    return {
        "id": "abc12345",
        "name": "Test E-reader",
        "hostname": hostname,
        "port": 22,
        "username": "root",
        "password": "",
        "ssh_key_path": "",
        "destination_path": "/mnt/us/books/",
    }


class TestEreaderStatusRoute:
    def test_unknown_ereader_404(self, client):
        with patch.object(ereaders_routes, "get_ereader_by_id", return_value=None):
            response = client.get("/api/ereaders/nope/status")
        assert response.status_code == 404

    def test_unconfigured_hostname(self, client):
        with patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config(hostname="")):
            response = client.get("/api/ereaders/abc12345/status")
        assert response.status_code == 200
        data = response.json()
        assert data["configured"] is False
        assert data["reachable"] is False
        assert data["checked_at"] is None

    @pytest.mark.parametrize("reachable", [True, False])
    def test_probe_result_returned(self, client, reachable):
        with (
            patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config()),
            patch.object(ereaders_routes.EreaderClient, "is_reachable", return_value=reachable),
        ):
            response = client.get("/api/ereaders/abc12345/status")
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
            patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config()),
            patch.object(ereaders_routes.EreaderClient, "is_reachable", fake_probe),
        ):
            first = client.get("/api/ereaders/abc12345/status")
            second = client.get("/api/ereaders/abc12345/status")

        assert first.json()["cached"] is False
        assert second.json()["cached"] is True
        assert len(probe_calls) == 1

    def test_refresh_bypasses_cache(self, client):
        probe_calls = []

        def fake_probe(self, timeout=None):
            probe_calls.append(1)
            return True

        with (
            patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config()),
            patch.object(ereaders_routes.EreaderClient, "is_reachable", fake_probe),
        ):
            client.get("/api/ereaders/abc12345/status")
            refreshed = client.get("/api/ereaders/abc12345/status?refresh=true")

        assert refreshed.json()["cached"] is False
        assert len(probe_calls) == 2
