"""Tests for Prowlarr RSS client methods: get_indexer_caps and fetch_rss."""

from datetime import UTC, datetime, timedelta
from email.utils import formatdate
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.prowlarr_client import ProwlarrClient


@pytest.fixture
def client():
    return ProwlarrClient(api_key="test_api_key", base_url="http://localhost:9696")


@pytest.fixture
def caps_with_book_search_xml():
    """Load the caps_with_book_search.xml fixture."""
    with open("tests/fixtures/rss/caps_with_book_search.xml") as f:
        return f.read()


@pytest.fixture
def caps_no_book_search_xml():
    """Load the caps_no_book_search.xml fixture."""
    with open("tests/fixtures/rss/caps_no_book_search.xml") as f:
        return f.read()


@pytest.fixture
def feed_valid_xml():
    """Load the feed_valid.xml fixture."""
    with open("tests/fixtures/rss/feed_valid.xml") as f:
        return f.read()


@pytest.fixture
def feed_missing_pubdate_xml():
    """Load the feed_missing_pubdate.xml fixture."""
    with open("tests/fixtures/rss/feed_missing_pubdate.xml") as f:
        return f.read()


class TestGetIndexerCaps:
    """Tests for ProwlarrClient.get_indexer_caps()."""

    def test_get_indexer_caps_book_search_supported(self, client, caps_with_book_search_xml):
        """Test caps fetch when book-search is available."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = caps_with_book_search_xml
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            result = client.get_indexer_caps(1)

        assert result["book_search_supported"] is True
        assert "categories" in result
        assert len(result["categories"]) > 0

    def test_get_indexer_caps_no_book_search(self, client, caps_no_book_search_xml):
        """Test caps fetch when book-search is not available."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = caps_no_book_search_xml
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            result = client.get_indexer_caps(2)

        assert result["book_search_supported"] is False
        assert "categories" in result

    def test_get_indexer_caps_http_error(self, client):
        """Test caps fetch when HTTP error occurs (500)."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
            mock_get.return_value = mock_response

            result = client.get_indexer_caps(3)

        assert result["book_search_supported"] is False
        assert "error" in result
        assert result["error"] is not None


class TestFetchRss:
    """Tests for ProwlarrClient.fetch_rss()."""

    def test_fetch_rss_happy_path(self, client, feed_valid_xml):
        """Test successful RSS fetch with valid feed."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = feed_valid_xml
            mock_response.headers = {}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "ok"
        assert meta["http_status"] == 200
        assert meta["error"] is None
        assert meta["retry_after_seconds"] is None
        assert len(items) == 3
        assert all("title" in item for item in items)
        assert all("guid" in item for item in items)

    def test_fetch_rss_429_with_retry_after_seconds(self, client):
        """Test RSS fetch with HTTP 429 and Retry-After in seconds."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "1800"}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "rate_limited"
        assert meta["http_status"] == 429
        assert meta["retry_after_seconds"] == 1800
        assert meta["error"] is None
        assert items == []

    def test_fetch_rss_429_with_retry_after_http_date(self, client):
        """Test RSS fetch with HTTP 429 and Retry-After as HTTP-date."""
        # Create a date 30 minutes in the future
        future_time = datetime.now(UTC) + timedelta(minutes=30)
        http_date = formatdate(timeval=future_time.timestamp(), localtime=False, usegmt=True)

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": http_date}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "rate_limited"
        assert meta["http_status"] == 429
        assert meta["retry_after_seconds"] is not None
        # Should be approximately 1800 seconds (30 minutes), allow some tolerance
        assert 1790 <= meta["retry_after_seconds"] <= 1810
        assert items == []

    def test_fetch_rss_500(self, client):
        """Test RSS fetch with HTTP 500 error."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "error"
        assert meta["http_status"] == 500
        assert meta["error"] is not None
        assert meta["retry_after_seconds"] is None
        assert items == []

    def test_fetch_rss_timeout(self, client):
        """Test RSS fetch when request times out."""
        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "error"
        assert meta["http_status"] is None
        assert meta["error"] is not None
        assert "timed out" in meta["error"].lower() or "timeout" in meta["error"].lower()
        assert items == []

    def test_fetch_rss_malformed_xml(self, client):
        """Test RSS fetch with malformed XML response."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "This is not valid XML at all <broken>"
            mock_response.headers = {}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        # Should not raise, should return empty items
        assert meta["status"] == "ok"
        assert items == []

    def test_fetch_rss_skips_items_missing_pubdate(self, client, feed_missing_pubdate_xml):
        """Test RSS fetch skips items with missing pubDate."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = feed_missing_pubdate_xml
            mock_response.headers = {}
            mock_get.return_value = mock_response

            items, meta = client.fetch_rss(1, "TestIndexer")

        assert meta["status"] == "ok"
        # Should have 2 items (the one with missing pubDate is skipped)
        assert len(items) == 2
        # Verify the skipped item is not in the results
        titles = [item.get("title") for item in items]
        assert "Brave New World by Aldous Huxley (EPUB) [MISSING PUBDATE]" not in titles
        # Verify the valid items are present
        assert any("1984" in title for title in titles)
        assert any("Fahrenheit 451" in title for title in titles)
