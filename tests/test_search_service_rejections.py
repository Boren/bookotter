# pyright: reportArgumentType=false

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes import search as search_routes
from backend.services.blocklist_service import BlocklistService
from backend.services.search_service import SearchService
from tests.helpers import create_test_book


def make_result(title="Book EPUB", seeders=10, size=2 * 1024 * 1024, guid="guid-1", **overrides):
    import hashlib

    hash_hex = hashlib.sha1(guid.encode()).hexdigest()
    result = {
        "guid": guid,
        "indexer_id": 1,
        "indexer": "TestIndexer",
        "title": title,
        "size": size,
        "seeders": seeders,
        "leechers": 2,
        "download_url": f"https://example.com/download/{guid}",
        "magnet_url": f"magnet:?xt=urn:btih:{hash_hex}&dn={title}",
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

        results = SearchService(prowlarr, db_session).search_book("Great Book audiobook EPUB")

        assert results[0].rejections == ["Audiobook"]
        assert results[0].approved is False

    def test_multi_cause_rejection(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(title="Great Book audiobook EPUB", seeders=0, size=5_000)]

        results = SearchService(prowlarr, db_session).search_book("Great Book audiobook EPUB")

        assert results[0].rejections == ["Audiobook", "No seeders", "Size too small"]

    def test_blocklisted_rejection(self, db_session):
        BlocklistService(db_session).add("TestIndexer", "guid-1", "Book EPUB")
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(guid="guid-1")]

        results = SearchService(prowlarr, db_session).search_book("Book EPUB")

        assert "Blocklisted" in results[0].rejections

    def test_no_seeder_rejection(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(seeders=0)]

        results = SearchService(prowlarr, db_session).search_book("Book EPUB")

        assert results[0].rejections == ["No seeders"]

    def test_size_too_small(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(size=9_999)]

        results = SearchService(prowlarr, db_session).search_book("Book EPUB")

        assert results[0].rejections == ["Size too small"]

    def test_size_too_large(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(size=600 * 1024 * 1024)]

        results = SearchService(prowlarr, db_session).search_book("Book EPUB")

        assert results[0].rejections == ["Size too large"]


class TestOmnibusSignals:
    def test_phrase_signals_detected(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("The First Law Trilogy EPUB") == {"trilogy"}
        assert omnibus_signals("Sherlock Holmes Omnibus") == {"omnibus"}
        assert omnibus_signals("The Cosmere Collection") == {"collection"}
        assert omnibus_signals("Complete Series Boxed Set") == {"complete-series", "box-set"}

    def test_numeric_range_signals_detected(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("Dungeon Crawler Carl Books 1-7") == {"book-range"}
        assert omnibus_signals("First Law #1-3 EPUB") == {"hash-range"}
        assert omnibus_signals("Mistborn Vols. 1-3") == {"vol-range"}

    def test_clean_titles_have_no_signals(self):
        from backend.services.search_service import omnibus_signals

        assert omnibus_signals("The Blade Itself (2006) EPUB") == set()
        assert omnibus_signals("This Inevitable Ruin - Book 7") == set()
        assert omnibus_signals("") == set()


class TestOmnibusRejection:
    def test_trilogy_rejected_for_single_volume_query(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="The First Law Trilogy by Joe Abercrombie EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "The Blade Itself", author="Joe Abercrombie"
        )

        assert "Omnibus/collection" in results[0].rejections
        assert results[0].approved is False

    def test_mistborn_trilogy_rejected(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Mistborn Trilogy by Brandon Sanderson EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "Mistborn: The Final Empire", author="Brandon Sanderson"
        )

        assert "Omnibus/collection" in results[0].rejections

    def test_book_range_rejected_for_single_volume_query(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Matt Dinniman - Dungeon Crawler Carl Books 1-7 EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "This Inevitable Ruin", author="Matt Dinniman"
        )

        assert "Omnibus/collection" in results[0].rejections

    def test_query_signal_suppressed(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="Arcanum Unbounded: The Cosmere Collection EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "Arcanum Unbounded: The Cosmere Collection", author="Brandon Sanderson"
        )

        assert results[0].approved is True
        assert results[0].rejections == []

    def test_single_volume_release_not_rejected(self, db_session):
        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            make_result(title="The Blade Itself by Joe Abercrombie EPUB")
        ]

        results = SearchService(prowlarr, db_session).search_book(
            "The Blade Itself", author="Joe Abercrombie"
        )

        assert results[0].approved is True

    def test_no_query_title_skips_guard(self, db_session):
        prowlarr = MagicMock()
        service = SearchService(prowlarr, db_session)

        filtered = service.filter_results([make_result(title="The First Law Trilogy EPUB")])

        assert len(filtered) == 1


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
        torrent_url = qbt.add_torrent.call_args.kwargs["torrent_url"]
        assert torrent_url.startswith("magnet:?xt=urn:btih:")

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

        results = SearchService(prowlarr, db_session).search_book("Book EPUB")

        assert results[0].approved is True
        assert results[0].rejections == []


class TestGrabRouteHashValidation:
    def test_auto_grab_no_hash_returns_failure(self, db_session):
        book = create_test_book(db_session, title="No Hash Book", author_name="Author")
        db_session.commit()

        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [
            {
                "guid": "no-hash-guid",
                "indexer_id": 1,
                "indexer": "TestIndexer",
                "title": "No Hash Book EPUB",
                "size": 2 * 1024 * 1024,
                "seeders": 10,
                "leechers": 2,
                "download_url": "https://example.com/download/no-hash",
                "magnet_url": None,
                "categories": [{"id": 7020, "name": "Books/Ebooks"}],
                "protocol": "torrent",
                "publish_date": "2024-01-15T00:00:00Z",
            }
        ]

        with patch("backend.api.routes.search._get_prowlarr_client", return_value=prowlarr):
            result = asyncio.run(search_routes.auto_search_and_grab(book.id, db_session))

        assert result["success"] is False
        message = result["message"].lower()
        assert "no usable magnet" in message or "hash" in message

    def test_grab_route_no_hash_raises_422(self, db_session):
        book = create_test_book(db_session, title="No Hash Book", author_name="Author")
        db_session.commit()

        body = search_routes.GrabRequest(
            book_id=book.id,
            result=search_routes.SearchResultItem(
                guid="no-hash-guid",
                indexer_id=1,
                indexer="TestIndexer",
                title="No Hash Book EPUB",
                size=2 * 1024 * 1024,
                seeders=10,
                leechers=2,
                download_url="https://example.com/download/no-hash",
                magnet_url=None,
                categories=[{"id": 7020, "name": "Books/Ebooks"}],
                protocol="torrent",
                publish_date="2024-01-15T00:00:00Z",
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(search_routes.grab_result(body, db_session))

        assert exc_info.value.status_code == 422
        assert "magnet" in exc_info.value.detail.lower() or "hash" in exc_info.value.detail.lower()


class TestAutoSearchExistingDownload:
    def test_existing_download_does_not_leave_book_searching(self, db_session):
        import hashlib

        from backend.models.book import Book, BookStatus, Download, DownloadStatus

        book = create_test_book(db_session, title="Great Book", author_name="Author")
        db_session.commit()
        hash_hex = hashlib.sha1(b"dupe").hexdigest()
        download = Download(
            book_id=book.id,
            torrent_hash=hash_hex,
            torrent_name="Great Book EPUB",
            indexer_name="TestIndexer",
            download_url="https://example.com/download/dupe",
            size=1000,
            seeders=5,
            status=DownloadStatus.COMPLETED.value,
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        prowlarr = MagicMock()
        prowlarr.search_book.return_value = [make_result(title="Great Book EPUB", guid="dupe")]
        qbt = MagicMock()

        with (
            patch("backend.api.routes.search._get_prowlarr_client", return_value=prowlarr),
            patch("backend.api.routes.search._get_qbittorrent_client", return_value=qbt),
            patch("backend.api.routes.search.load_config", return_value={"qbittorrent": {"category": "books"}}),
        ):
            result = asyncio.run(search_routes.auto_search_and_grab(book_id, db_session))

        assert result["success"] is False
        assert "already exists" in result["message"]
        db_session.expire_all()
        assert db_session.get(Book, book_id).status != BookStatus.SEARCHING.value
