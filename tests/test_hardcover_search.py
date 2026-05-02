"""Tests for HardcoverClient.search_books used by the scanner bootstrap path."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.clients.hardcover_client import HardcoverClient
from backend.errors import FailureReason, PipelineError


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


def _make_search_response(results: object, ids: list[int] | None = None, error: str | None = None) -> dict:
    return {
        "data": {
            "search": {
                "ids": ids if ids is not None else [],
                "results": results,
                "error": error,
                "page": 1,
                "per_page": 5,
            }
        }
    }


def _book_entry(book_id: int, title: str, authors: list[str] | None = None, isbns: list[str] | None = None) -> dict:
    return {
        "id": book_id,
        "title": title,
        "author_names": authors if authors is not None else [],
        "isbns": isbns if isbns is not None else [],
    }


class TestHardcoverSearchBooks:
    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_returns_results_when_search_succeeds(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [
            _book_entry(101, "The Name of the Wind", ["Patrick Rothfuss"], ["9780756404741"]),
            _book_entry(102, "The Wise Man's Fear", ["Patrick Rothfuss"], ["9780756407919"]),
            _book_entry(103, "The Slow Regard of Silent Things", ["Patrick Rothfuss"], []),
        ]
        mock_post.return_value = _make_response(200, _make_search_response(results, ids=[101, 102, 103]))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("name of the wind")

        assert len(books) == 3
        assert books[0] == {
            "id": 101,
            "title": "The Name of the Wind",
            "author_names": ["Patrick Rothfuss"],
            "isbns": ["9780756404741"],
        }
        assert books[1]["id"] == 102
        assert books[2]["isbns"] == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_returns_empty_list_when_no_results(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response([], ids=[]))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("zzzzz nothing matches")

        assert books == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_returns_empty_list_when_results_field_is_null(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response(None))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("anything")

        assert books == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_respects_limit_parameter(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [_book_entry(i, f"Book {i}", [f"Author {i}"], []) for i in range(1, 11)]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("test", limit=3)

        assert len(books) == 3
        assert mock_post.call_args.kwargs["json"]["variables"]["perPage"] == 3

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_default_limit_is_five(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response([]))

        client = HardcoverClient(api_token="test_token")
        client.search_books("anything")

        assert mock_post.call_args.kwargs["json"]["variables"]["perPage"] == 5

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_query_string_passed_correctly_to_graphql(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response([]))

        client = HardcoverClient(api_token="test_token")
        client.search_books("Brandon Sanderson Mistborn")

        sent = mock_post.call_args.kwargs["json"]
        assert sent["variables"]["query"] == "Brandon Sanderson Mistborn"
        assert "search(" in sent["query"]
        assert 'query_type: "book"' in sent["query"]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_results_field_as_json_string(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [_book_entry(42, "Dune", ["Frank Herbert"], ["9780441172719"])]
        mock_post.return_value = _make_response(200, _make_search_response(json.dumps(results)))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("dune")

        assert len(books) == 1
        assert books[0]["id"] == 42
        assert books[0]["title"] == "Dune"
        assert books[0]["isbns"] == ["9780441172719"]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_results_field_as_list(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [_book_entry(7, "Foundation", ["Isaac Asimov"], [])]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("foundation")

        assert len(books) == 1
        assert books[0]["id"] == 7

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_typesense_hits_wrapper(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        wrapped = {"hits": [_book_entry(99, "Wrapped Book", ["Author X"], ["1234567890"])]}
        mock_post.return_value = _make_response(200, _make_search_response(wrapped))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("wrapped")

        assert len(books) == 1
        assert books[0]["id"] == 99
        assert books[0]["title"] == "Wrapped Book"

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_typesense_document_nesting(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [{"document": _book_entry(50, "Nested Book", ["Author Y"], ["9999999999"])}]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("nested")

        assert len(books) == 1
        assert books[0]["id"] == 50
        assert books[0]["title"] == "Nested Book"
        assert books[0]["author_names"] == ["Author Y"]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_skips_malformed_results_gracefully(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [
            _book_entry(1, "Good Book", ["Author"], []),
            {"id": 2},  # missing title
            {"title": "No ID"},  # missing id
            "not a dict",  # wrong type
            _book_entry(3, "Another Good Book", ["Author"], []),
        ]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("test")

        assert len(books) == 2
        ids = [b["id"] for b in books]
        assert ids == [1, 3]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_skips_entry_with_non_integer_id(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [
            _book_entry(1, "Valid"),
            {"id": "not-an-int", "title": "Bad ID"},
            _book_entry(2, "Also Valid"),
        ]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("test")

        assert [b["id"] for b in books] == [1, 2]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_extracts_isbns_when_present(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [_book_entry(10, "Has ISBNs", ["A"], ["9780001112225", "9780001112226"])]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("has isbns")

        assert books[0]["isbns"] == ["9780001112225", "9780001112226"]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_extracts_isbns_as_empty_list_when_absent(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [{"id": 11, "title": "No ISBN field", "author_names": ["B"]}]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("no isbn")

        assert books[0]["isbns"] == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_extracts_authors_as_empty_list_when_absent(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [{"id": 12, "title": "No author field"}]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("no author")

        assert books[0]["author_names"] == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_filters_out_empty_authors_and_isbns(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        results = [{"id": 13, "title": "Mixed", "author_names": ["A", "", None], "isbns": ["123", "", None]}]
        mock_post.return_value = _make_response(200, _make_search_response(results))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("mixed")

        assert books[0]["author_names"] == ["A"]
        assert books[0]["isbns"] == ["123"]

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_unparseable_json_string_gracefully(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response("{not valid json"))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("anything")

        assert books == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_handles_unexpected_results_shape_gracefully(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response(42))

        client = HardcoverClient(api_token="test_token")
        books = client.search_books("anything")

        assert books == []

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_propagates_auth_failure(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(401)

        client = HardcoverClient(api_token="bad_token")
        with pytest.raises(PipelineError) as exc_info:
            client.search_books("anything")

        assert exc_info.value.reason == FailureReason.HARDCOVER_AUTH_FAILED
        assert mock_post.call_count == 1

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_propagates_forbidden(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(403)

        client = HardcoverClient(api_token="bad_token")
        with pytest.raises(PipelineError) as exc_info:
            client.search_books("anything")

        assert exc_info.value.reason == FailureReason.HARDCOVER_AUTH_FAILED

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_propagates_network_error(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError("connection refused")

        client = HardcoverClient(api_token="test_token")
        with pytest.raises(PipelineError) as exc_info:
            client.search_books("anything")

        assert exc_info.value.reason == FailureReason.HARDCOVER_UNREACHABLE

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_uses_bearer_auth_header(self, mock_post: MagicMock, mock_sleep: MagicMock) -> None:
        mock_post.return_value = _make_response(200, _make_search_response([]))

        client = HardcoverClient(api_token="my-secret-token")
        client.search_books("anything")

        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "my-secret-token"

    @patch("backend.clients.hardcover_client.time.sleep")
    @patch("backend.clients.hardcover_client.requests.post")
    def test_logs_warning_when_search_returns_error_field(
        self, mock_post: MagicMock, mock_sleep: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        results = [_book_entry(1, "Partial result")]
        mock_post.return_value = _make_response(200, _make_search_response(results, error="Partial index unavailable"))

        client = HardcoverClient(api_token="test_token")
        with caplog.at_level("WARNING", logger="backend.clients.hardcover_client"):
            books = client.search_books("anything")

        assert len(books) == 1
        assert any("Partial index unavailable" in rec.message for rec in caplog.records)
