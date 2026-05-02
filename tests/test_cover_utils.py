"""
Tests for backend.utils.cover module.
"""

import logging
from unittest.mock import MagicMock, patch

from backend.utils.cover import fetch_cover


class TestFetchCoverBasic:
    """Basic input validation tests."""

    def test_fetch_cover_none_url(self):
        """fetch_cover(None) returns None without logging."""
        result = fetch_cover(None)
        assert result is None

    def test_fetch_cover_empty_string(self):
        """fetch_cover("") returns None without logging."""
        result = fetch_cover("")
        assert result is None


class TestFetchCoverSuccess:
    """Successful fetch scenarios."""

    def test_successful_fetch_jpeg(self):
        """Successful fetch returns (bytes, content_type)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": "1024",
        }
        mock_response.iter_content = lambda chunk_size: iter([b"x" * 1024])

        with patch("requests.get", return_value=mock_response):
            result = fetch_cover("https://example.com/cover.jpg")

        assert result is not None
        assert result[0] == b"x" * 1024
        assert result[1] == "image/jpeg"

    def test_successful_fetch_png(self):
        """Successful fetch with PNG content type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/png",
        }
        mock_response.iter_content = lambda chunk_size: iter([b"png_data"])

        with patch("requests.get", return_value=mock_response):
            result = fetch_cover("https://example.com/cover.png")

        assert result is not None
        assert result[0] == b"png_data"
        assert result[1] == "image/png"

    def test_successful_fetch_multiple_chunks(self):
        """Successful fetch with multiple chunks."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/webp",
        }
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        mock_response.iter_content = lambda chunk_size: iter(chunks)

        with patch("requests.get", return_value=mock_response):
            result = fetch_cover("https://example.com/cover.webp")

        assert result is not None
        assert result[0] == b"chunk1chunk2chunk3"
        assert result[1] == "image/webp"

    def test_content_type_case_insensitive(self):
        """Content-Type validation is case-insensitive."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "IMAGE/JPEG",
        }
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response):
            result = fetch_cover("https://example.com/cover.jpg")

        assert result is not None
        assert result[1] == "image/jpeg"


class TestFetchCoverHTTPErrors:
    """HTTP error scenarios."""

    def test_404_not_found(self, caplog):
        """404 status returns None and logs WARNING."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"Content-Type": "text/html"}

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/missing.jpg")

        assert result is None
        assert "non-2xx status" in caplog.text.lower()
        assert "404" in caplog.text

    def test_500_server_error(self, caplog):
        """500 status returns None and logs WARNING."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {"Content-Type": "text/html"}

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/error.jpg")

        assert result is None
        assert "non-2xx status" in caplog.text.lower()


class TestFetchCoverContentType:
    """Content-Type validation tests."""

    def test_non_image_content_type_html(self, caplog):
        """Non-image Content-Type returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.iter_content = lambda chunk_size: iter([b"<html>"])

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/page.html")

        assert result is None
        assert "non-image content type" in caplog.text.lower()

    def test_non_image_content_type_json(self, caplog):
        """JSON Content-Type returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.iter_content = lambda chunk_size: iter([b"{}"])

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/data.json")

        assert result is None

    def test_missing_content_type_header(self, caplog):
        """Missing Content-Type header returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/cover.jpg")

        assert result is None


class TestFetchCoverSizeValidation:
    """Size validation tests."""

    def test_content_length_exceeds_10mb(self, caplog):
        """Content-Length > 10MB returns None without reading body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": str(11 * 1024 * 1024),  # 11 MB
        }
        mock_response.iter_content = MagicMock()  # Should not be called

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/large.jpg")

        assert result is None
        assert "too large" in caplog.text.lower()
        # Verify iter_content was not called
        mock_response.iter_content.assert_not_called()

    def test_streaming_body_exceeds_10mb(self, caplog):
        """Streaming body exceeding 10MB cap returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/jpeg",
            # No Content-Length header
        }
        # Simulate streaming chunks that exceed 10MB
        chunk_size = 1024 * 1024  # 1 MB chunks
        chunks = [b"x" * chunk_size for _ in range(12)]  # 12 MB total
        mock_response.iter_content = lambda chunk_size: iter(chunks)

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/large.jpg")

        assert result is None
        assert "exceeds 10mb cap" in caplog.text.lower()

    def test_streaming_body_at_10mb_boundary(self):
        """Streaming body exactly at 10MB boundary succeeds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/jpeg",
        }
        # Exactly 10 MB
        chunk_size = 1024 * 1024  # 1 MB chunks
        chunks = [b"x" * chunk_size for _ in range(10)]  # 10 MB total
        mock_response.iter_content = lambda chunk_size: iter(chunks)

        with patch("requests.get", return_value=mock_response):
            result = fetch_cover("https://example.com/large.jpg")

        assert result is not None
        assert len(result[0]) == 10 * 1024 * 1024


class TestFetchCoverNetworkErrors:
    """Network error scenarios."""

    def test_connection_refused(self, caplog):
        """Connection refused returns None and logs WARNING."""
        import requests

        with patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        ):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/cover.jpg")

        assert result is None
        assert "failed to fetch" in caplog.text.lower()

    def test_timeout(self, caplog):
        """Timeout returns None and logs WARNING."""
        import requests

        with patch(
            "requests.get",
            side_effect=requests.exceptions.Timeout("Request timed out"),
        ):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/cover.jpg", timeout=5.0)

        assert result is None
        assert "failed to fetch" in caplog.text.lower()

    def test_request_exception(self, caplog):
        """Generic RequestException returns None and logs WARNING."""
        import requests

        with patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("Network error"),
        ):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/cover.jpg")

        assert result is None
        assert "failed to fetch" in caplog.text.lower()

    def test_streaming_error(self, caplog):
        """Error during streaming returns None and logs WARNING."""
        import requests

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "image/jpeg",
        }
        mock_response.iter_content = MagicMock(
            side_effect=requests.exceptions.RequestException("Stream error"),
        )

        with patch("requests.get", return_value=mock_response):
            with caplog.at_level(logging.WARNING):
                result = fetch_cover("https://example.com/cover.jpg")

        assert result is None
        assert "error streaming" in caplog.text.lower()


class TestFetchCoverCustomTimeout:
    """Custom timeout parameter tests."""

    def test_custom_timeout_passed_to_requests(self):
        """Custom timeout is passed to requests.get."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response) as mock_get:
            fetch_cover("https://example.com/cover.jpg", timeout=15.0)

        # Verify timeout was passed
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["timeout"] == 15.0

    def test_default_timeout(self):
        """Default timeout is 10.0 seconds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response) as mock_get:
            fetch_cover("https://example.com/cover.jpg")

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["timeout"] == 10.0


class TestFetchCoverRequestParameters:
    """Verify correct request parameters."""

    def test_stream_true_parameter(self):
        """stream=True is passed to requests.get."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response) as mock_get:
            fetch_cover("https://example.com/cover.jpg")

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["stream"] is True

    def test_allow_redirects_true(self):
        """allow_redirects=True is passed to requests.get."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content = lambda chunk_size: iter([b"data"])

        with patch("requests.get", return_value=mock_response) as mock_get:
            fetch_cover("https://example.com/cover.jpg")

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["allow_redirects"] is True
