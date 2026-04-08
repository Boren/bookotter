from unittest.mock import MagicMock, patch

import pytest

from backend.services.search_service import PREFERRED_SIZE_MAX, PREFERRED_SIZE_MIN, SearchService


def make_result(title="Book Title.epub", seeders=10, size=None, guid="guid-1"):
    return {
        "guid": guid,
        "indexer_id": 1,
        "indexer": "TestIndexer",
        "title": title,
        "size": size if size is not None else PREFERRED_SIZE_MIN,
        "seeders": seeders,
        "leechers": 2,
        "download_url": "https://example.com/download/1",
        "magnet_url": None,
        "categories": [{"id": 7020, "name": "Books/Ebooks"}],
        "protocol": "torrent",
        "publish_date": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def mock_prowlarr():
    return MagicMock()


@pytest.fixture
def service(mock_prowlarr):
    return SearchService(prowlarr_client=mock_prowlarr)


class TestSearchBook:
    def test_returns_ranked_epub_results(self, service, mock_prowlarr):
        epub_result = make_result("Great Book.epub", seeders=5)
        mobi_result = make_result("Great Book.mobi", seeders=20)
        mock_prowlarr.search_book.return_value = [epub_result, mobi_result]

        results = service.search_book("Great Book")

        assert len(results) == 1
        assert results[0]["title"] == "Great Book.epub"

    def test_passes_title_and_author_to_prowlarr(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = []

        service.search_book("Dune", author="Frank Herbert")

        mock_prowlarr.search_book.assert_called_once_with(title="Dune", author="Frank Herbert")

    def test_returns_empty_when_prowlarr_returns_nothing(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = []

        results = service.search_book("Nonexistent Book")

        assert results == []

    def test_returns_empty_when_all_results_filtered(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [
            make_result("Book.pdf"),
            make_result("Book.mobi"),
        ]

        results = service.search_book("Some Book")

        assert results == []

    def test_results_are_ranked_by_seeders_descending(self, service, mock_prowlarr):
        low = make_result("Book.epub", seeders=5, guid="low")
        high = make_result("Another.epub", seeders=50, guid="high")
        mock_prowlarr.search_book.return_value = [low, high]

        results = service.search_book("Book")

        assert results[0]["guid"] == "high"
        assert results[1]["guid"] == "low"

    def test_author_defaults_to_empty_string(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = []

        service.search_book("Only Title")

        mock_prowlarr.search_book.assert_called_once_with(title="Only Title", author="")


class TestFilterResults:
    def test_keeps_epub_results(self, service):
        results = [make_result("Book.epub")]
        assert service.filter_results(results) == results

    def test_removes_non_epub_results(self, service):
        results = [make_result("Book.pdf"), make_result("Book.mobi"), make_result("Book.azw3")]
        assert service.filter_results(results) == []

    def test_epub_detection_is_case_insensitive(self, service):
        results = [make_result("Book.EPUB"), make_result("Book.Epub")]
        filtered = service.filter_results(results)
        assert len(filtered) == 2

    def test_mixed_formats_keeps_only_epub(self, service):
        epub = make_result("Good.epub", guid="epub")
        pdf = make_result("Bad.pdf", guid="pdf")
        filtered = service.filter_results([epub, pdf])
        assert len(filtered) == 1
        assert filtered[0]["guid"] == "epub"

    def test_empty_list_returns_empty(self, service):
        assert service.filter_results([]) == []

    def test_none_title_is_not_epub(self, service):
        result = make_result()
        result["title"] = None
        assert service.filter_results([result]) == []


class TestRankResults:
    def test_sorted_by_seeders_descending(self, service):
        a = make_result(seeders=5, guid="a")
        b = make_result(seeders=50, guid="b")
        c = make_result(seeders=20, guid="c")

        ranked = service.rank_results([a, b, c])

        assert [r["guid"] for r in ranked] == ["b", "c", "a"]

    def test_preferred_size_breaks_tie_in_favor_of_in_range(self, service):
        preferred_size = (PREFERRED_SIZE_MIN + PREFERRED_SIZE_MAX) // 2
        oversized = make_result(seeders=10, size=PREFERRED_SIZE_MAX * 2, guid="big")
        in_range = make_result(seeders=10, size=preferred_size, guid="good")

        ranked = service.rank_results([oversized, in_range])

        assert ranked[0]["guid"] == "good"
        assert ranked[1]["guid"] == "big"

    def test_higher_seeders_beats_preferred_size(self, service):
        preferred_size = (PREFERRED_SIZE_MIN + PREFERRED_SIZE_MAX) // 2
        many_seeds_large = make_result(seeders=100, size=PREFERRED_SIZE_MAX * 2, guid="big")
        few_seeds_small = make_result(seeders=5, size=preferred_size, guid="small")

        ranked = service.rank_results([few_seeds_small, many_seeds_large])

        assert ranked[0]["guid"] == "big"

    def test_empty_list_returns_empty(self, service):
        assert service.rank_results([]) == []

    def test_none_seeders_treated_as_zero(self, service):
        no_seeds = make_result(seeders=None, guid="none")
        with_seeds = make_result(seeders=1, guid="one")

        ranked = service.rank_results([no_seeds, with_seeds])

        assert ranked[0]["guid"] == "one"

    def test_size_boundary_min_is_preferred(self, service):
        at_min = make_result(seeders=10, size=PREFERRED_SIZE_MIN, guid="min")
        below_min = make_result(seeders=10, size=PREFERRED_SIZE_MIN - 1, guid="below")

        ranked = service.rank_results([below_min, at_min])

        assert ranked[0]["guid"] == "min"

    def test_size_boundary_max_is_preferred(self, service):
        at_max = make_result(seeders=10, size=PREFERRED_SIZE_MAX, guid="max")
        above_max = make_result(seeders=10, size=PREFERRED_SIZE_MAX + 1, guid="above")

        ranked = service.rank_results([above_max, at_max])

        assert ranked[0]["guid"] == "max"
