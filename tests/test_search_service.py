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


class TestUnknownVerdictRejection:
    def test_unknown_verdict_without_epub_is_rejected(self, service, mock_prowlarr):
        result = make_result(
            title="Some Generic Book Title",
            categories=[{"id": 7020, "name": "Books/Ebooks"}],
        )
        mock_prowlarr.search_book.return_value = [result]

        results = service.search_book("Some Generic Book Title")

        assert results[0].approved is False
        assert "No candidate matches title" in results[0].rejections

    def test_unknown_verdict_with_epub_filename_is_approved(self, service, mock_prowlarr):
        result = make_result(
            title="Some Generic Book Title.epub",
            categories=[{"id": 7020, "name": "Books/Ebooks"}],
        )
        mock_prowlarr.search_book.return_value = [result]

        results = service.search_book("Some Generic Book Title.epub")

        assert results[0].approved is True
        assert results[0].rejections == []


class TestAudiobookRegexFalsePositive:
    def test_read_by_moonlight_not_flagged_as_audiobook(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [make_result(title="Read by Moonlight EPUB")]

        results = service.search_book("Read by Moonlight EPUB")

        assert "Audiobook" not in results[0].rejections
        assert results[0].approved is True

    def test_actual_audiobook_with_narrator_credit_still_rejected(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [make_result(title="Foundation - Read by Author Name")]

        results = service.search_book("Foundation - Read by Author Name")

        assert "Audiobook" in results[0].rejections


class TestSimilarityFiltering:
    def test_high_similarity_match_is_approved(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [make_result(title="Foundation EPUB")]

        results = service.search_book("Foundation EPUB")

        assert results[0].approved is True
        assert results[0].title_similarity >= 0.75

    def test_low_similarity_no_author_match_is_rejected(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [make_result(title="Pride and Prejudice EPUB")]

        results = service.search_book("Foundation")

        assert results[0].approved is False
        assert "No candidate matches title" in results[0].rejections
        assert results[0].title_similarity < 0.75

    def test_low_similarity_with_author_match_passes(self, service, mock_prowlarr):
        mock_prowlarr.search_book.return_value = [
            make_result(
                title="Some Different Title EPUB",
                author="Frank Herbert",
            )
        ]

        results = service.search_book("Dune", author="Frank Herbert")

        assert results[0].author_match is True
        assert "No candidate matches title" not in results[0].rejections


class TestSimilarityRanking:
    def test_higher_similarity_outranks_higher_seeders(self, service, mock_prowlarr):
        better_match_low_seeders = make_result(
            title="Foundation EPUB",
            guid="better-match",
            seeders=5,
        )
        worse_match_high_seeders = make_result(
            title="Foundation EPUB v2 Extended",
            guid="worse-match",
            seeders=50,
        )
        mock_prowlarr.search_book.return_value = [worse_match_high_seeders, better_match_low_seeders]

        results = service.search_book("Foundation EPUB")

        assert results[0].guid == "better-match"
        assert results[1].guid == "worse-match"
        assert results[0].title_similarity > results[1].title_similarity

    def test_author_match_outranks_no_author_match(self, service, mock_prowlarr):
        no_author = make_result(title="Foundation EPUB", guid="no-author", seeders=100)
        with_author = make_result(
            title="Foundation EPUB",
            guid="with-author",
            seeders=5,
            author="Isaac Asimov",
        )
        mock_prowlarr.search_book.return_value = [no_author, with_author]

        results = service.search_book("Foundation EPUB", author="Isaac Asimov")

        assert results[0].guid == "with-author"
        assert results[0].author_match is True
        assert results[1].author_match is False
