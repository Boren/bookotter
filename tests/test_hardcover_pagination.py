"""Tests for HardcoverClient pagination and retry/backoff behavior."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.hardcover_client import HARDCOVER_PAGE_SIZE, HardcoverClient
from backend.constants import HARDCOVER_RETRY_ATTEMPTS, HARDCOVER_TIMEOUT
from backend.errors import FailureReason, PipelineError


def _make_book_node(book_id: int, title: str = "Sample") -> dict:
    return {
        "status_id": 1,
        "rating": None,
        "date_added": "2026-01-01",
        "book": {
            "id": book_id,
            "title": title,
            "slug": f"book-{book_id}",
            "subtitle": "",
            "cached_contributors": None,
            "image": {"url": None},
            "book_series": [],
            "editions": [],
            "contributions": [],
        },
    }


def _make_page(book_nodes: list[dict]) -> dict:
    return {"data": {"me": [{"user_books": book_nodes}]}}


def _make_response(
    status_code: int,
    json_data: dict | None = None,
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.reason = "OK" if resp.ok else "Error"
    resp.headers = headers or {}
    resp.json.return_value = json_data or {}
    return resp


class TestPagination:
    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_multi_page_fetches_all_books(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page1 = _make_page([_make_book_node(i) for i in range(1, HARDCOVER_PAGE_SIZE + 1)])
        page2 = _make_page([_make_book_node(i) for i in range(HARDCOVER_PAGE_SIZE + 1, HARDCOVER_PAGE_SIZE + 31)])

        mock_post.side_effect = [
            _make_response(200, page1),
            _make_response(200, page2),
        ]

        client = HardcoverClient(api_token="test_token")
        books = client.get_books_by_status([1])

        assert len(books) == HARDCOVER_PAGE_SIZE + 30
        assert mock_post.call_count == 2

        call1_vars = mock_post.call_args_list[0].kwargs["json"]["variables"]
        call2_vars = mock_post.call_args_list[1].kwargs["json"]["variables"]
        assert call1_vars["limit"] == HARDCOVER_PAGE_SIZE
        assert call1_vars["offset"] == 0
        assert call2_vars["limit"] == HARDCOVER_PAGE_SIZE
        assert call2_vars["offset"] == HARDCOVER_PAGE_SIZE

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_single_partial_page_stops_after_one_request(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page1 = _make_page([_make_book_node(i) for i in range(1, 11)])
        mock_post.return_value = _make_response(200, page1)

        client = HardcoverClient(api_token="test_token")
        books = client.get_books_by_status([1])

        assert len(books) == 10
        assert mock_post.call_count == 1

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_three_pages_all_full_then_partial(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page1 = _make_page([_make_book_node(i) for i in range(1, HARDCOVER_PAGE_SIZE + 1)])
        page2 = _make_page([_make_book_node(i) for i in range(HARDCOVER_PAGE_SIZE + 1, 2 * HARDCOVER_PAGE_SIZE + 1)])
        page3 = _make_page(
            [_make_book_node(i) for i in range(2 * HARDCOVER_PAGE_SIZE + 1, 2 * HARDCOVER_PAGE_SIZE + 6)]
        )

        mock_post.side_effect = [
            _make_response(200, page1),
            _make_response(200, page2),
            _make_response(200, page3),
        ]

        client = HardcoverClient(api_token="test_token")
        books = client.get_books_by_status([1])

        assert len(books) == 2 * HARDCOVER_PAGE_SIZE + 5
        assert mock_post.call_count == 3
        offsets = [c.kwargs["json"]["variables"]["offset"] for c in mock_post.call_args_list]
        assert offsets == [0, HARDCOVER_PAGE_SIZE, 2 * HARDCOVER_PAGE_SIZE]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_dedup_across_pages_same_hardcover_id(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page1 = _make_page([_make_book_node(i) for i in range(1, HARDCOVER_PAGE_SIZE + 1)])
        page2 = _make_page([_make_book_node(i) for i in range(46, 76)])

        mock_post.side_effect = [
            _make_response(200, page1),
            _make_response(200, page2),
        ]

        client = HardcoverClient(api_token="test_token")
        books = client.get_books_by_status([1])

        unique_ids = {b["hardcover_id"] for b in books}
        assert len(unique_ids) == 75
        assert len(books) == 75

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_empty_first_page_returns_empty_list(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_page([]))

        client = HardcoverClient(api_token="test_token")
        books = client.get_books_by_status([1])

        assert books == []
        assert mock_post.call_count == 1


class TestRetryAndRateLimit:
    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_429_with_retry_after_sleeps_exact_seconds_then_retries(
        self, mock_post: MagicMock, mock_sleep: MagicMock
    ) -> None:
        page = _make_page([_make_book_node(1)])
        mock_post.side_effect = [
            _make_response(429, {}, headers={"Retry-After": "5"}),
            _make_response(200, page),
        ]

        client = HardcoverClient(api_token="test_token")
        result = client._make_request("query { me { id } }")

        assert mock_post.call_count == 2
        sleep_durations = [c.args[0] for c in mock_sleep.call_args_list]
        assert 5.0 in sleep_durations
        assert result == page

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_429_without_retry_after_uses_fallback_delay(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page = _make_page([_make_book_node(1)])
        mock_post.side_effect = [
            _make_response(429, {}, headers={}),
            _make_response(200, page),
        ]

        client = HardcoverClient(api_token="test_token")
        result = client._make_request("query { me { id } }")

        assert mock_post.call_count == 2
        assert result == page

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_429_persistent_raises_rate_limited(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(429, {}, headers={"Retry-After": "1"})

        client = HardcoverClient(api_token="test_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_RATE_LIMITED
        assert mock_post.call_count == HARDCOVER_RETRY_ATTEMPTS

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_401_raises_immediately_no_retry(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(401)

        client = HardcoverClient(api_token="bad_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_AUTH_FAILED
        assert mock_post.call_count == 1

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_403_raises_immediately_no_retry(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(403)

        client = HardcoverClient(api_token="bad_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_AUTH_FAILED
        assert mock_post.call_count == 1

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_timeout_retries_then_raises_unreachable(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.side_effect = requests.exceptions.Timeout("read timeout")

        client = HardcoverClient(api_token="test_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_UNREACHABLE
        assert mock_post.call_count == HARDCOVER_RETRY_ATTEMPTS

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_connection_error_retries_then_raises_unreachable(
        self, mock_post: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError("connection refused")

        client = HardcoverClient(api_token="test_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_UNREACHABLE
        assert mock_post.call_count == HARDCOVER_RETRY_ATTEMPTS

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_transient_timeout_then_success(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        page = _make_page([_make_book_node(1)])
        mock_post.side_effect = [
            requests.exceptions.Timeout("transient"),
            _make_response(200, page),
        ]

        client = HardcoverClient(api_token="test_token")
        result = client._make_request("query { me { id } }")

        assert result == page
        assert mock_post.call_count == 2

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_request_uses_hardcover_timeout_constant(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_page([]))

        client = HardcoverClient(api_token="test_token")
        client._make_request("query { me { id } }")

        assert mock_post.call_args.kwargs["timeout"] == HARDCOVER_TIMEOUT

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_500_retries_as_unreachable(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(500)

        client = HardcoverClient(api_token="test_token")
        with pytest.raises(PipelineError) as exc_info:
            client._make_request("query { me { id } }")

        assert exc_info.value.reason == FailureReason.HARDCOVER_UNREACHABLE
        assert mock_post.call_count == HARDCOVER_RETRY_ATTEMPTS
