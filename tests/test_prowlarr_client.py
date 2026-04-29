"""Tests for the Prowlarr API client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.prowlarr_client import BOOK_CATEGORY_ID, ProwlarrClient


@pytest.fixture
def client():
    return ProwlarrClient(api_key="test_api_key", base_url="http://localhost:9696")


@pytest.fixture
def sample_search_result():
    return {
        "guid": "https://example.com/release/12345",
        "indexerId": 1,
        "indexer": "TestIndexer",
        "title": "The Great Book - Author Name",
        "size": 1048576,
        "seeders": 10,
        "leechers": 2,
        "downloadUrl": "https://example.com/download/12345",
        "magnetUrl": "magnet:?xt=urn:btih:abc123",
        "categories": [{"id": 7020, "name": "Books/Ebooks"}],
        "protocol": "torrent",
        "publishDate": "2024-01-15T00:00:00Z",
    }


class TestProwlarrClientInit:
    def test_init_sets_attributes(self):
        c = ProwlarrClient(api_key="mykey", base_url="http://prowlarr:9696/")
        assert c.api_key == "mykey"
        assert c.base_url == "http://prowlarr:9696"
        assert c.headers == {"X-Api-Key": "mykey"}

    def test_init_default_base_url(self):
        c = ProwlarrClient(api_key="key")
        assert c.base_url == "http://localhost:9696"

    def test_init_strips_trailing_slash(self):
        c = ProwlarrClient(api_key="key", base_url="http://host:9696///")
        assert c.base_url == "http://host:9696"


class TestMakeRequest:
    def test_make_request_success(self, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"version": "1.0"}
        mock_response.raise_for_status.return_value = None

        with patch("requests.request", return_value=mock_response) as mock_req:
            result = client._make_request("/api/v1/system/status")

        mock_req.assert_called_once_with(
            method="GET",
            url="http://localhost:9696/api/v1/system/status",
            headers={"X-Api-Key": "test_api_key"},
            params=None,
            json=None,
            timeout=30,
        )
        assert result == {"version": "1.0"}

    def test_make_request_raises_on_http_error(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)

        with patch("requests.request", return_value=mock_response):
            from backend.errors import FailureReason, PipelineError

            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v1/search")
            assert exc_info.value.reason == FailureReason.PROWLARR_AUTH_FAILED

    def test_make_request_raises_on_timeout(self, client):
        with patch("requests.request", side_effect=requests.exceptions.Timeout("timed out")):
            from backend.errors import FailureReason, PipelineError

            with pytest.raises(PipelineError) as exc_info:
                client._make_request("/api/v1/search")
            assert exc_info.value.reason == FailureReason.PROWLARR_UNREACHABLE

    def test_make_request_passes_params(self, client):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        params = {"query": "test", "type": "book"}
        with patch("requests.request", return_value=mock_response) as mock_req:
            client._make_request("/api/v1/search", params=params)

        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["params"] == params


class TestNormalizeResult:
    def test_normalize_maps_all_fields(self, client, sample_search_result):
        normalized = client._normalize_result(sample_search_result)

        assert normalized["guid"] == sample_search_result["guid"]
        assert normalized["indexer_id"] == sample_search_result["indexerId"]
        assert normalized["indexer"] == sample_search_result["indexer"]
        assert normalized["title"] == sample_search_result["title"]
        assert normalized["size"] == sample_search_result["size"]
        assert normalized["seeders"] == sample_search_result["seeders"]
        assert normalized["leechers"] == sample_search_result["leechers"]
        assert normalized["download_url"] == sample_search_result["downloadUrl"]
        assert normalized["magnet_url"] == sample_search_result["magnetUrl"]
        assert normalized["categories"] == sample_search_result["categories"]
        assert normalized["protocol"] == sample_search_result["protocol"]
        assert normalized["publish_date"] == sample_search_result["publishDate"]

    def test_normalize_handles_missing_fields(self, client):
        normalized = client._normalize_result({})

        assert normalized["guid"] is None
        assert normalized["indexer_id"] is None
        assert normalized["title"] is None
        assert normalized["categories"] == []


class TestSearch:
    def test_search_returns_normalized_results(self, client, sample_search_result):
        with patch.object(client, "_make_request", return_value=[sample_search_result]):
            results = client.search("Great Book")

        assert len(results) == 1
        assert results[0]["title"] == sample_search_result["title"]
        assert results[0]["indexer_id"] == sample_search_result["indexerId"]

    def test_search_empty_results(self, client):
        with patch.object(client, "_make_request", return_value=[]):
            results = client.search("nonexistent book xyz")

        assert results == []

    def test_search_uses_default_book_category(self, client):
        with patch.object(client, "_make_request", return_value=[]) as mock_req:
            client.search("test query")

        params = mock_req.call_args.kwargs["params"]
        assert BOOK_CATEGORY_ID in params["categories"]

    def test_search_returns_empty_on_exception(self, client):
        with patch.object(client, "_make_request", side_effect=requests.exceptions.ConnectionError("refused")):
            results = client.search("test")

        assert results == []

    def test_search_custom_limit(self, client):
        with patch.object(client, "_make_request", return_value=[]) as mock_req:
            client.search("test", limit=50)

        params = mock_req.call_args.kwargs["params"]
        assert params["limit"] == 50

    def test_search_returns_empty_on_none_response(self, client):
        with patch.object(client, "_make_request", return_value=None):
            results = client.search("test")

        assert results == []


class TestSearchBook:
    def test_search_book_title_only(self, client, sample_search_result):
        with patch.object(client, "_make_request", return_value=[sample_search_result]) as mock_req:
            results = client.search_book("The Great Book")

        params = mock_req.call_args.kwargs["params"]
        assert params["query"] == "The Great Book"
        assert params["type"] == "book"
        assert len(results) == 1

    def test_search_book_title_and_author(self, client):
        with patch.object(client, "_make_request", return_value=[]) as mock_req:
            client.search_book("The Great Book", author="Jane Author")

        params = mock_req.call_args.kwargs["params"]
        assert params["query"] == "The Great Book Jane Author"

    def test_search_book_empty_author_not_appended(self, client):
        with patch.object(client, "_make_request", return_value=[]) as mock_req:
            client.search_book("My Book", author="")

        params = mock_req.call_args.kwargs["params"]
        assert params["query"] == "My Book"

    def test_search_book_returns_empty_on_exception(self, client):
        with patch.object(client, "_make_request", side_effect=requests.exceptions.Timeout("timeout")):
            results = client.search_book("test")

        assert results == []

    def test_search_book_uses_book_category(self, client):
        with patch.object(client, "_make_request", return_value=[]) as mock_req:
            client.search_book("test")

        params = mock_req.call_args.kwargs["params"]
        assert BOOK_CATEGORY_ID in params["categories"]


class TestGetIndexers:
    def test_get_indexers_returns_list(self, client):
        indexers = [{"id": 1, "name": "NZBGeek"}, {"id": 2, "name": "TorrentLeech"}]
        with patch.object(client, "_make_request", return_value=indexers):
            result = client.get_indexers()

        assert result == indexers

    def test_get_indexers_returns_empty_on_none(self, client):
        with patch.object(client, "_make_request", return_value=None):
            result = client.get_indexers()

        assert result == []

    def test_get_indexers_returns_empty_on_exception(self, client):
        with patch.object(client, "_make_request", side_effect=requests.exceptions.ConnectionError("refused")):
            result = client.get_indexers()

        assert result == []


class TestTestConnection:
    def test_test_connection_success(self, client):
        with patch.object(client, "_make_request", return_value={"version": "1.12.0"}):
            result = client.test_connection()

        assert result["success"] is True
        assert "1.12.0" in result["message"]

    def test_test_connection_auth_failure(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = requests.exceptions.HTTPError(response=mock_response)

        with patch.object(client, "_make_request", side_effect=http_error):
            result = client.test_connection()

        assert result["success"] is False
        assert result["error_type"] == "auth_failed"
        assert "Prowlarr" in result["error"]

    def test_test_connection_timeout(self, client):
        with patch.object(client, "_make_request", side_effect=requests.exceptions.Timeout("timed out")):
            result = client.test_connection()

        assert result["success"] is False
        assert result["error_type"] == "timeout"

    def test_test_connection_invalid_response(self, client):
        with patch.object(client, "_make_request", return_value=None):
            result = client.test_connection()

        assert result["success"] is False
        assert result["error_type"] == "invalid_response"

    def test_test_connection_connection_error(self, client):
        with patch.object(
            client, "_make_request", side_effect=requests.exceptions.ConnectionError("connection refused")
        ):
            result = client.test_connection()

        assert result["success"] is False
        assert result["error_type"] == "network_error"
