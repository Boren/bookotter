"""Tests for the qBittorrent API client."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.qbittorrent_client import (
    DOWNLOAD_COMPLETE_STATES,
    QBittorrentClient,
    TorrentState,
)


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


class TestLogin:
    def test_login_success_stores_authenticated(self, client):
        ok_resp = _mock_response(200, "Ok.")
        with patch.object(client._session, "post", return_value=ok_resp):
            client._login()
        assert client._authenticated is True

    def test_login_wrong_credentials_raises(self, client):
        fails_resp = _mock_response(200, "Fails.")
        with patch.object(client._session, "post", return_value=fails_resp):
            with pytest.raises(RuntimeError, match="invalid username or password"):
                client._login()
        assert client._authenticated is False

    def test_login_403_raises_banned(self, client):
        banned_resp = _mock_response(403, "")
        with patch.object(client._session, "post", return_value=banned_resp):
            with pytest.raises(RuntimeError, match="403"):
                client._login()


class TestEnsureAuthenticated:
    def test_calls_login_when_not_authenticated(self, client):
        with patch.object(client, "_login") as mock_login:
            client._ensure_authenticated()
        mock_login.assert_called_once()

    def test_does_not_call_login_when_fresh_session(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        with patch.object(client, "_login") as mock_login:
            client._ensure_authenticated()
        mock_login.assert_not_called()

    def test_reauths_when_session_expired(self, client):
        client._authenticated = True
        client._auth_time = 0.0
        with patch.object(client, "_login") as mock_login:
            client._ensure_authenticated()
        mock_login.assert_called_once()


class TestAddTorrent:
    def test_add_torrent_returns_true_on_ok(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "Ok.")
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.add_torrent("magnet:?xt=urn:btih:abc123")
        assert result is True

    def test_add_torrent_with_category_passes_data(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "Ok.")
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            client.add_torrent("magnet:?xt=urn:btih:abc123", category="books")
        _, kwargs = mock_req.call_args
        assert kwargs["data"]["category"] == "books"

    def test_add_torrent_returns_false_on_exception(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        with patch.object(client._session, "request", side_effect=requests.exceptions.ConnectionError("fail")):
            result = client.add_torrent("magnet:?xt=urn:btih:abc123")
        assert result is False


class TestGetTorrents:
    def test_get_torrents_returns_list(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        torrent_data = [{"hash": "abc123", "state": "downloading", "progress": 0.5}]
        ok_resp = _mock_response(200, json_data=torrent_data)
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.get_torrents()
        assert result == torrent_data

    def test_get_torrents_by_hash_passes_pipe_joined_hashes(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, json_data=[])
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            client.get_torrents(hashes=["aaa", "bbb"])
        _, kwargs = mock_req.call_args
        assert kwargs["params"]["hashes"] == "aaa|bbb"

    def test_get_torrents_returns_empty_list_on_error(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        with patch.object(client._session, "request", side_effect=requests.exceptions.Timeout()):
            result = client.get_torrents()
        assert result == []


class TestGetTorrentFiles:
    def test_get_files_returns_list(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        files_data = [{"name": "book.epub", "size": 1024, "priority": 1}]
        ok_resp = _mock_response(200, json_data=files_data)
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.get_torrent_files("abc123")
        assert result == files_data


class TestGetTorrentProperties:
    def test_returns_dict_on_success(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        props = {"save_path": "/downloads/", "total_size": 2048}
        ok_resp = _mock_response(200, json_data=props)
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.get_torrent_properties("abc123")
        assert result == props

    def test_returns_none_on_404(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        not_found = _mock_response(404, "")
        http_err = requests.exceptions.HTTPError(response=not_found)
        not_found.raise_for_status.side_effect = http_err
        with patch.object(client._session, "request", return_value=not_found):
            result = client.get_torrent_properties("missing")
        assert result is None


class TestSetFilePriority:
    def test_set_priority_returns_true_on_success(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "")
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.set_file_priority("abc123", [0, 2], priority=0)
        assert result is True

    def test_set_priority_joins_file_ids_with_pipe(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "")
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            client.set_file_priority("abc123", [1, 3, 5], priority=7)
        _, kwargs = mock_req.call_args
        assert kwargs["data"]["id"] == "1|3|5"
        assert kwargs["data"]["priority"] == 7


class TestDeleteTorrent:
    def test_delete_without_files(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "")
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            result = client.delete_torrent("abc123", delete_files=False)
        assert result is True
        _, kwargs = mock_req.call_args
        assert kwargs["data"]["deleteFiles"] == "false"

    def test_delete_with_files(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "")
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            result = client.delete_torrent("abc123", delete_files=True)
        assert result is True
        _, kwargs = mock_req.call_args
        assert kwargs["data"]["deleteFiles"] == "true"


class TestEnsureCategoryExists:
    def test_creates_new_category(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "")
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.ensure_category_exists("books")
        assert result is True

    def test_returns_true_when_409_category_exists(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        conflict_resp = _mock_response(409, "")
        http_err = requests.exceptions.HTTPError(response=conflict_resp)
        conflict_resp.raise_for_status.side_effect = http_err
        with patch.object(client._session, "request", return_value=conflict_resp):
            result = client.ensure_category_exists("books")
        assert result is True

    def test_returns_false_on_other_http_error(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        server_err = _mock_response(500, "")
        http_err = requests.exceptions.HTTPError(response=server_err)
        server_err.raise_for_status.side_effect = http_err
        with patch.object(client._session, "request", return_value=server_err):
            result = client.ensure_category_exists("books")
        assert result is False


class TestTestConnection:
    def test_successful_connection(self, client):
        login_resp = _mock_response(200, "Ok.")
        version_resp = _mock_response(200, "5.0.0")
        with (
            patch.object(client._session, "post", return_value=login_resp),
            patch.object(client._session, "request", return_value=version_resp),
        ):
            result = client.test_connection()
        assert result["success"] is True
        assert "5.0.0" in result["message"]

    def test_bad_credentials_returns_auth_failed(self, client):
        login_resp = _mock_response(200, "Fails.")
        with patch.object(client._session, "post", return_value=login_resp):
            result = client.test_connection()
        assert result["success"] is False
        assert result["error_type"] == "auth_failed"

    def test_network_error_returns_error_result(self, client):
        with patch.object(client._session, "post", side_effect=requests.exceptions.ConnectionError("refused")):
            result = client.test_connection()
        assert result["success"] is False


class TestGetCompletedFilePath:
    def _patch_torrents(self, client, torrent_data, files_data=None):
        with (
            patch.object(client, "get_torrents", return_value=torrent_data),
            patch.object(client, "get_torrent_files", return_value=files_data or []) as mock_files,
        ):
            yield mock_files

    def test_returns_none_when_torrent_not_found(self, client):
        with patch.object(client, "get_torrents", return_value=[]):
            result = client.get_completed_file_path("abc123")
        assert result is None

    def test_returns_none_when_still_downloading(self, client):
        torrent = {"state": TorrentState.DOWNLOADING, "progress": 0.5, "content_path": ""}
        with patch.object(client, "get_torrents", return_value=[torrent]):
            result = client.get_completed_file_path("abc123")
        assert result is None

    def test_returns_single_epub_from_content_path(self, client):
        torrent = {
            "state": TorrentState.UPLOADING,
            "progress": 1.0,
            "content_path": "/downloads/book.epub",
            "save_path": "/downloads/",
        }
        with patch.object(client, "get_torrents", return_value=[torrent]):
            result = client.get_completed_file_path("abc123")
        assert result == Path("/downloads/book.epub")

    def test_finds_epub_in_multi_file_torrent(self, client):
        torrent = {
            "state": TorrentState.STALLED_UP,
            "progress": 1.0,
            "content_path": "/downloads/bundle/",
            "save_path": "/downloads/",
        }
        files = [
            {"name": "bundle/book.mobi", "priority": 0},
            {"name": "bundle/book.epub", "priority": 1},
            {"name": "bundle/cover.jpg", "priority": 0},
        ]
        with (
            patch.object(client, "get_torrents", return_value=[torrent]),
            patch.object(client, "get_torrent_files", return_value=files),
        ):
            result = client.get_completed_file_path("abc123")
        assert result == Path("/downloads/bundle/book.epub")

    def test_returns_none_when_no_epub_in_torrent(self, client):
        torrent = {
            "state": TorrentState.PAUSED_UP,
            "progress": 1.0,
            "content_path": "/downloads/audiobook/",
            "save_path": "/downloads/",
        }
        files = [
            {"name": "audiobook/part1.mp3", "priority": 1},
        ]
        with (
            patch.object(client, "get_torrents", return_value=[torrent]),
            patch.object(client, "get_torrent_files", return_value=files),
        ):
            result = client.get_completed_file_path("abc123")
        assert result is None

    def test_progress_1_counts_as_complete(self, client):
        torrent = {
            "state": TorrentState.PAUSED_DL,
            "progress": 1.0,
            "content_path": "/downloads/book.epub",
            "save_path": "/downloads/",
        }
        with patch.object(client, "get_torrents", return_value=[torrent]):
            result = client.get_completed_file_path("abc123")
        assert result == Path("/downloads/book.epub")


class TestSessionReauth:
    def test_retries_once_on_403_during_request(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0

        forbidden_resp = _mock_response(403, "Forbidden")
        http_err = requests.exceptions.HTTPError(response=forbidden_resp)
        forbidden_resp.raise_for_status.side_effect = http_err

        ok_resp = _mock_response(200, json_data=[])

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return forbidden_resp
            return ok_resp

        login_resp = _mock_response(200, "Ok.")
        with (
            patch.object(client._session, "request", side_effect=side_effect),
            patch.object(client._session, "post", return_value=login_resp),
        ):
            result = client.get_torrents()

        assert call_count == 2
        assert result == []


class TestTorrentStateEnum:
    def test_completed_states_set_contains_expected_values(self):
        assert TorrentState.UPLOADING in DOWNLOAD_COMPLETE_STATES
        assert TorrentState.STALLED_UP in DOWNLOAD_COMPLETE_STATES
        assert TorrentState.PAUSED_UP in DOWNLOAD_COMPLETE_STATES
        assert TorrentState.DOWNLOADING not in DOWNLOAD_COMPLETE_STATES
        assert TorrentState.ERROR not in DOWNLOAD_COMPLETE_STATES


class TestAddTorrentFile:
    def test_returns_true_on_ok(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "Ok.")
        with patch.object(client._session, "request", return_value=ok_resp):
            result = client.add_torrent_file(b"d4:infod4:name1:xee", category="books")
        assert result is True

    def test_uploads_bytes_and_category(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        ok_resp = _mock_response(200, "Ok.")
        with patch.object(client._session, "request", return_value=ok_resp) as mock_req:
            client.add_torrent_file(b"torrentbytes", category="books")
        _, kwargs = mock_req.call_args
        assert kwargs["data"]["category"] == "books"
        assert kwargs["files"]["torrents"][1] == b"torrentbytes"

    def test_returns_false_on_exception(self, client):
        client._authenticated = True
        client._auth_time = 9999999999.0
        with patch.object(client._session, "request", side_effect=requests.exceptions.ConnectionError("fail")):
            result = client.add_torrent_file(b"torrentbytes")
        assert result is False


class TestAddTorrentQbit51JsonResponse:
    """qBittorrent >= 5.1 returns JSON from /torrents/add instead of 'Ok.'."""

    def _client_with_response(self, client, body: str):
        client._authenticated = True
        client._auth_time = 9999999999.0
        return patch.object(client._session, "request", return_value=_mock_response(200, body))

    def test_add_torrent_pending_is_success(self, client):
        body = '{"added_torrent_ids":[],"failure_count":0,"pending_count":1,"success_count":0}'
        with self._client_with_response(client, body):
            assert client.add_torrent("http://prowlarr.example/download?id=1") is True

    def test_add_torrent_success_count_is_success(self, client):
        body = '{"added_torrent_ids":["abc"],"failure_count":0,"pending_count":0,"success_count":1}'
        with self._client_with_response(client, body):
            assert client.add_torrent("magnet:?xt=urn:btih:" + "a" * 40) is True

    def test_add_torrent_failure_count_is_failure(self, client):
        body = '{"added_torrent_ids":[],"failure_count":1,"pending_count":0,"success_count":0}'
        with self._client_with_response(client, body):
            assert client.add_torrent("magnet:?xt=urn:btih:" + "a" * 40) is False

    def test_add_torrent_file_json_success(self, client):
        body = '{"added_torrent_ids":["abc"],"failure_count":0,"pending_count":0,"success_count":1}'
        with self._client_with_response(client, body):
            assert client.add_torrent_file(b"torrentbytes") is True

    def test_legacy_ok_still_success(self, client):
        with self._client_with_response(client, "Ok."):
            assert client.add_torrent("magnet:?xt=urn:btih:" + "a" * 40) is True

    def test_legacy_fails_still_failure(self, client):
        with self._client_with_response(client, "Fails."):
            assert client.add_torrent("magnet:?xt=urn:btih:" + "a" * 40) is False
