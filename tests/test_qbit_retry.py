"""Tests for qBittorrent client retry behavior with exponential backoff."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.qbittorrent_client import QBittorrentClient
from backend.errors import FailureReason, PipelineError


@pytest.fixture
def client():
    return QBittorrentClient(
        username="admin",
        password="adminadmin",
        base_url="http://localhost:8080",
    )


def _mock_response(status_code: int = 200, text: str = "", json_data=None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestConnectionRetryWithBackoff:
    """Test retry_with_backoff wrapping for connection errors."""

    def test_connection_error_retried_then_succeeds(self, client):
        """ConnectionError is retried, eventual success returns data."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        call_count = [0]

        def mock_request(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise requests.exceptions.ConnectionError("Connection refused")
            resp = _mock_response(200, json_data=[{"hash": "abc123"}])
            return resp

        with patch.object(client._session, "request", side_effect=mock_request):
            result = client.get_torrents()

        assert call_count[0] == 3
        assert result == [{"hash": "abc123"}]

    def test_timeout_error_retried_then_succeeds(self, client):
        """Timeout is retried, eventual success returns data."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        call_count = [0]

        def mock_request(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise requests.exceptions.Timeout("Request timeout")
            resp = _mock_response(200, json_data=[])
            return resp

        with patch.object(client._session, "request", side_effect=mock_request):
            result = client.get_torrents()

        assert call_count[0] == 2
        assert result == []

    def test_connection_timeout_exhausts_retries_raises_qbit_unreachable(self, client):
        """Timeout exhausts all retries and raises PipelineError with QBIT_UNREACHABLE."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        with patch.object(
            client._session, "request", side_effect=requests.exceptions.Timeout("timeout")
        ):
            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v2/torrents/info")

            assert exc_info.value.reason == FailureReason.QBIT_UNREACHABLE
            assert "timeout" in str(exc_info.value).lower()

    def test_connection_refused_exhausts_retries_raises_qbit_unreachable(self, client):
        """ConnectionError exhausts all retries and raises PipelineError with QBIT_UNREACHABLE."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        with patch.object(
            client._session, "request", side_effect=requests.exceptions.ConnectionError("refused")
        ):
            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v2/torrents/info")

            assert exc_info.value.reason == FailureReason.QBIT_UNREACHABLE


class TestAuthRetryComposedWithConnectionRetry:
    """Test that auth retry (403) and connection retry compose correctly."""

    def test_403_triggers_reauth_then_succeeds(self, client):
        """403 triggers re-auth, then succeeds — connection retry not triggered."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        forbidden_resp = _mock_response(403, "Forbidden")
        http_err = requests.exceptions.HTTPError(response=forbidden_resp)
        forbidden_resp.raise_for_status.side_effect = http_err

        ok_resp = _mock_response(200, json_data=[{"hash": "xyz789"}])

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return forbidden_resp
            return ok_resp

        login_resp = _mock_response(200, "Ok.")
        with (
            patch.object(client._session, "request", side_effect=side_effect),
            patch.object(client._session, "post", return_value=login_resp),
        ):
            result = client.get_torrents()

        assert call_count[0] == 2
        assert result == [{"hash": "xyz789"}]

    def test_401_after_reauth_raises_qbit_auth_failed(self, client):
        """401 after re-auth attempt raises PipelineError with QBIT_AUTH_FAILED."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        unauthorized_resp = _mock_response(401, "Unauthorized")
        http_err = requests.exceptions.HTTPError(response=unauthorized_resp)
        unauthorized_resp.raise_for_status.side_effect = http_err

        login_resp = _mock_response(200, "Ok.")

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            return unauthorized_resp

        with (
            patch.object(client._session, "request", side_effect=side_effect),
            patch.object(client._session, "post", return_value=login_resp),
        ):
            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v2/torrents/info")

            assert exc_info.value.reason == FailureReason.QBIT_AUTH_FAILED
            assert "401" in str(exc_info.value)

    def test_connection_error_during_403_reauth_retries(self, client):
        """Connection error during 403 re-auth flow is retried."""
        client._authenticated = True
        client._auth_time = 9999999999.0

        forbidden_resp = _mock_response(403, "Forbidden")
        http_err = requests.exceptions.HTTPError(response=forbidden_resp)
        forbidden_resp.raise_for_status.side_effect = http_err

        ok_resp = _mock_response(200, json_data=[])

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return forbidden_resp
            elif call_count[0] == 2:
                raise requests.exceptions.ConnectionError("Connection lost during re-auth")
            return ok_resp

        login_resp = _mock_response(200, "Ok.")
        with (
            patch.object(client._session, "request", side_effect=side_effect),
            patch.object(client._session, "post", return_value=login_resp),
        ):
            result = client.get_torrents()

        assert call_count[0] == 3
        assert result == []
