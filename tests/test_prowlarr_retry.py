"""Tests for Prowlarr client retry behavior."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.prowlarr_client import ProwlarrClient
from backend.errors import FailureReason, PipelineError


class TestProwlarrRetry:
    def test_503_retried_then_succeeds(self):
        """Transient 503 is retried, eventual success returns data."""
        client = ProwlarrClient(api_key="test", base_url="http://localhost:9696")

        call_count = [0]

        def mock_request(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                resp = MagicMock()
                resp.status_code = 503
                resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
                return resp
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            resp.json.return_value = []
            return resp

        with patch("requests.request", side_effect=mock_request):
            result = client._make_request("/api/v1/search", params={"query": "test"})
            assert result == []

    def test_401_raises_immediately(self):
        """401 raises PipelineError immediately without retry."""
        client = ProwlarrClient(api_key="bad_key", base_url="http://localhost:9696")

        call_count = [0]

        def mock_request(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 401
            return resp

        with patch("requests.request", side_effect=mock_request):
            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v1/search")
            assert exc_info.value.reason == FailureReason.PROWLARR_AUTH_FAILED
            assert call_count[0] == 1

    def test_timeout_exhausts_retries(self):
        """Connection timeout exhausts retries and raises PROWLARR_UNREACHABLE."""
        client = ProwlarrClient(api_key="test", base_url="http://localhost:9696")

        with patch("requests.request", side_effect=requests.exceptions.ConnectionError("timeout")):
            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v1/search")
            assert exc_info.value.reason == FailureReason.PROWLARR_UNREACHABLE
