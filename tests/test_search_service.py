from unittest.mock import MagicMock

import pytest

from backend.services.search_service import SearchService


def make_result(title="Book EPUB", seeders=10, size=2 * 1024 * 1024, guid="guid-1", **overrides):
    result = {
        "guid": guid,
        "indexer_id": 1,
        "indexer": "TestIndexer",
        "title": title,
        "size": size,
        "seeders": seeders,
        "leechers": 2,
        "download_url": "https://example.com/download/1",
        "magnet_url": None,
        "categories": [{"id": 7020, "name": "Books/Ebooks"}],
        "protocol": "torrent",
        "publish_date": "2024-01-15T00:00:00Z",
    }
    result.update(overrides)
    return result


@pytest.fixture
def mock_prowlarr():
    return MagicMock()


@pytest.fixture
def service(mock_prowlarr):
    return SearchService(prowlarr_client=mock_prowlarr)


class TestSearchBook:
    def test_returns_all_results_with_approval_markers(self, service, mock_prowlarr):
        approved = make_result(title="Great Book EPUB", guid="approved")
        rejected = make_result(title="Great Book.pdf", guid="rejected")
        mock_prowlarr.search_book.return_value = [rejected, approved]

        results = service.search_book("Great Book")

        assert len(results) == 2
        assert results[0].guid == "approved"
        assert results[0].approved is True
        assert results[1].guid == "rejected"
        assert results[1].approved is False

    def test_passes_title_and_author_to_prowlarr(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = []

        service.search_book("Dune", author="Frank Herbert")

        mock_prowlarr.search_book.assert_called_once_with(title="Dune", author="Frank Herbert")

    def test_returns_empty_when_prowlarr_returns_nothing(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = []

        results = service.search_book("Nonexistent Book")

        assert results == []


class TestCompatibilityHelpers:
    def test_filter_results_returns_serialized_scored_results(self, service):
        filtered = service.filter_results([make_result(title="Book.pdf")])

        assert len(filtered) == 1
        assert filtered[0]["approved"] is False
        assert filtered[0]["rejections"] == ["Non-EPUB format detected (non-EPUB format tag: pdf (no EPUB found))"]

    def test_rank_results_sorts_approved_before_rejected(self, service):
        approved = make_result(guid="approved")
        rejected = make_result(guid="rejected", title="Book.pdf")

        ranked = service.rank_results([rejected, approved])

        assert ranked[0]["guid"] == "approved"
        assert ranked[1]["guid"] == "rejected"
