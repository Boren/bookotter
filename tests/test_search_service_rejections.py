# pyright: reportArgumentType=false

import asyncio
from unittest.mock import MagicMock, patch

from backend.api.routes import search as search_routes
from backend.services.blocklist_service import BlocklistService
from backend.services.search_service import SearchService
from tests.helpers import create_test_book


def make_result(title="Book EPUB", seeders=10, size=2 * 1024 * 1024, guid="guid-1", **overrides):
    result = {
        "guid": guid,
        "indexer_id": 1,
        "indexer": "TestIndexer",
        "title": title,
        "size": size,
        "seeders": seeders,
        "leechers": 2,
        "download_url": f"https://example.com/download/{guid}",
        "magnet_url": None,
        "categories": [{"id": 7020, "name": "Books/Ebooks"}],
        "protocol": "torrent",
        "publish_date": "2024-01-15T00:00:00Z",
    }
    result.update(overrides)
    return result


class TestRejections:
    def test_audiobook_rejection(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(title="Great Book audiobook EPUB")]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].rejections == ["Audiobook"]
        assert results[0].approved is False

    def test_multi_cause_rejection(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(title="Great Book audiobook EPUB", seeders=0, size=5_000)]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].rejections == ["Audiobook", "No seeders", "Size too small"]

    def test_blocklisted_rejection(self, db_session):
        BlocklistService(db_session).add("TestIndexer", "guid-1", "Great Book EPUB")
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(guid="guid-1")]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert "Blocklisted" in results[0].rejections

    def test_no_seeder_rejection(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(seeders=0)]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].rejections == ["No seeders"]

    def test_size_too_small(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(size=9_999)]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].rejections == ["Size too small"]

    def test_size_too_large(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(size=600 * 1024 * 1024)]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].rejections == ["Size too large"]


class TestAutoSearch:
    def test_auto_search_skips_rejected(self, db_session):
        book = create_test_book(db_session, title="Great Book", author_name="Author")
        db_session.commit()

        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Great Book audiobook EPUB", guid="audio", seeders=20),
            make_result(title="Great Book.pdf", guid="pdf", seeders=15),
            make_result(title="Great Book EPUB", guid="noseed", seeders=0),
            make_result(title="Great Book EPUB", guid="approved", seeders=5),
        ]
        qbt = MagicMock()
        qbt.add_torrent.return_value = True

        with (
            patch("backend.api.routes.search._get_prowlarr_client", return_value=prowlarr),
            patch("backend.api.routes.search._get_qbittorrent_client", return_value=qbt),
            patch("backend.api.routes.search.load_config", return_value={"qbittorrent": {"category": "books"}}),
        ):
            result = asyncio.run(search_routes.auto_search_and_grab(book.id, db_session))

        assert result["success"] is True
        assert result["result_title"] == "Great Book EPUB"
        assert qbt.add_torrent.call_args.kwargs["torrent_url"] == "https://example.com/download/approved"

    def test_auto_search_all_rejected(self, db_session):
        book = create_test_book(db_session, title="Great Book", author_name="Author")
        db_session.commit()

        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Great Book audiobook EPUB", guid="audio"),
            make_result(title="Great Book.pdf", guid="pdf"),
            make_result(title="Great Book EPUB", guid="noseed", seeders=0),
        ]
        qbt = MagicMock()

        with (
            patch("backend.api.routes.search._get_prowlarr_client", return_value=prowlarr),
            patch("backend.api.routes.search._get_qbittorrent_client", return_value=qbt),
            patch("backend.api.routes.search.load_config", return_value={"qbittorrent": {"category": "books"}}),
        ):
            result = asyncio.run(search_routes.auto_search_and_grab(book.id, db_session))

        assert result == {
            "success": False,
            "message": "No approved results found",
            "book_id": book.id,
            "results_count": 3,
        }
        qbt.add_torrent.assert_not_called()

    def test_approved_result_has_empty_rejections(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(guid="approved")]

        results = SearchService(prowlarr, db_session).search_book("Great Book")

        assert results[0].approved is True
        assert results[0].rejections == []
