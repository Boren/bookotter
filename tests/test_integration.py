"""End-to-end integration tests for the BookOtter book management pipeline."""

import os
from unittest.mock import MagicMock

from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.hardcover_sync_service import HardcoverSyncService
from backend.services.pipeline_service import PipelineService
from tests.helpers import create_test_book, create_test_epub


def make_pipeline(db_session, search_service=None, download_service=None, import_service=None):
    return PipelineService(
        search_service=search_service,
        download_service=download_service,
        import_service=import_service,
        db_session_factory=lambda: db_session,
    )


def refresh_book(db, book_id):
    db.expire_all()
    return db.get(Book, book_id)


def refresh_download(db, download_id):
    db.expire_all()
    return db.get(Download, download_id)


def make_search_result(guid="abc-123", title="Book [EPUB]", indexer="TestIndexer", seeders=50, size=1_048_576):
    return {
        "guid": guid,
        "title": title,
        "indexer": indexer,
        "seeders": seeders,
        "size": size,
        "download_url": f"https://example.com/torrent/{guid}",
        "magnet_url": None,
    }


class TestFullPipelineHappyPath:
    def test_wanted_to_in_library(self, db_session, tmp_library):
        """WANTED book reaches IN_LIBRARY through all pipeline stages in one run."""
        book = create_test_book(db_session, title="Foundation", author_name="Isaac Asimov")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [
            make_search_result(guid="foundation-guid", title="Foundation - Isaac Asimov [EPUB]")
        ]

        epub_path = str(tmp_library / "downloads" / "Foundation.epub")
        os.makedirs(os.path.dirname(epub_path), exist_ok=True)
        create_test_epub(epub_path, "Foundation", "Isaac Asimov")

        mock_download = MagicMock()
        mock_download.add_torrent.return_value = True
        mock_download.get_completed_file_path.return_value = epub_path

        mock_import = MagicMock()
        mock_import.import_epub.return_value = True

        pipeline = make_pipeline(db_session, mock_search, mock_download, mock_import)
        results = pipeline.run_pipeline()

        final = refresh_book(db_session, book_id)
        assert final.status == BookStatus.IN_LIBRARY
        assert final.search_attempts == 1
        assert results["wanted"] == 1
        assert results["grabbed"] == 1
        assert results["downloading"] == 1
        assert results["importing"] == 1

        dl = final.downloads[0]
        assert dl.status == DownloadStatus.IMPORTED
        assert dl.file_path == epub_path

    def test_services_called_with_correct_args(self, db_session):
        """Each service receives the right data from the previous stage."""
        create_test_book(db_session, title="Dune", author_name="Frank Herbert")
        db_session.commit()

        captured_download = {}
        captured_import = {}

        def capture_add_torrent(download):
            captured_download["torrent_name"] = download.torrent_name
            captured_download["type"] = type(download).__name__
            return True

        def capture_import_epub(book, file_path):
            captured_import["title"] = book.title
            captured_import["file_path"] = file_path
            return True

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(guid="dune-guid")]

        mock_download = MagicMock()
        mock_download.add_torrent.side_effect = capture_add_torrent
        mock_download.get_completed_file_path.return_value = "/tmp/Dune.epub"

        mock_import = MagicMock()
        mock_import.import_epub.side_effect = capture_import_epub

        pipeline = make_pipeline(db_session, mock_search, mock_download, mock_import)
        pipeline.run_pipeline()

        mock_search.search_book.assert_called_once_with("Dune", "Frank Herbert")

        assert captured_download["type"] == "Download"
        assert captured_download["torrent_name"] == "Book [EPUB]"

        assert captured_import["title"] == "Dune"
        assert captured_import["file_path"] == "/tmp/Dune.epub"


class TestPipelineSearchFailures:
    def test_no_search_results_marks_failed(self, db_session):
        """Book returns to WANTED when search returns no results."""
        book = create_test_book(db_session, title="Nonexistent Book")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = []

        pipeline = make_pipeline(db_session, search_service=mock_search)
        results = pipeline.run_pipeline()

        final = refresh_book(db_session, book_id)
        assert final.status == BookStatus.WANTED
        assert final.search_attempts >= 1
        assert results["wanted"] == 0

    def test_search_exception_marks_failed(self, db_session):
        """Book transitions to FAILED when search service throws."""
        book = create_test_book(db_session, title="Error Book")
        db_session.commit()
        book_id = book.id

        mock_search = MagicMock()
        mock_search.search_book.side_effect = ConnectionError("Prowlarr unreachable")

        pipeline = make_pipeline(db_session, search_service=mock_search)
        pipeline.run_pipeline()

        assert refresh_book(db_session, book_id).status == BookStatus.FAILED


class TestPipelineDownloadFailures:
    def test_add_torrent_returns_false(self, db_session):
        """Book and download marked FAILED when add_torrent returns False."""
        book = create_test_book(db_session, title="Failing Download", status=BookStatus.GRABBED)
        download = Download(
            book_id=book.id,
            torrent_hash="deadbeef12345678ab0",
            torrent_name="Failing.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent/fail",
            size=1_000_000,
            seeders=5,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_download = MagicMock()
        mock_download.add_torrent.return_value = False

        pipeline = make_pipeline(db_session, download_service=mock_download)
        pipeline.run_pipeline()

        assert refresh_book(db_session, book_id).status == BookStatus.FAILED
        assert refresh_download(db_session, dl_id).status == DownloadStatus.FAILED

    def test_download_exception_preserves_error_message(self, db_session):
        """Error message from download exception is recorded on the download record."""
        book = create_test_book(db_session, title="qBit Error", status=BookStatus.GRABBED)
        download = Download(
            book_id=book.id,
            torrent_hash="qbiterr12345678ab01",
            torrent_name="Error.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent/err",
            size=500_000,
            seeders=3,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(download)
        db_session.commit()
        dl_id = download.id

        mock_download = MagicMock()
        mock_download.add_torrent.side_effect = ConnectionError("qBittorrent unreachable")

        pipeline = make_pipeline(db_session, download_service=mock_download)
        pipeline.run_pipeline()

        dl = refresh_download(db_session, dl_id)
        assert dl.status == DownloadStatus.FAILED
        assert "qBittorrent unreachable" in dl.error_message


class TestPipelineImportFailures:
    def test_import_exception_marks_failed(self, db_session):
        """Book marked FAILED when import_epub raises an exception."""
        book = create_test_book(db_session, title="Bad EPUB", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="badepub1234567890ab",
            torrent_name="Bad.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent/bad",
            size=500_000,
            seeders=10,
            status=DownloadStatus.COMPLETED,
            file_path="/tmp/bad.epub",
        )
        db_session.add(download)
        db_session.commit()
        book_id, dl_id = book.id, download.id

        mock_import = MagicMock()
        mock_import.import_epub.side_effect = Exception("Invalid EPUB structure")

        pipeline = make_pipeline(db_session, import_service=mock_import)
        pipeline.run_pipeline()

        assert refresh_book(db_session, book_id).status == BookStatus.FAILED
        dl = refresh_download(db_session, dl_id)
        assert dl.status == DownloadStatus.FAILED
        assert "Invalid EPUB structure" in dl.error_message

    def test_import_returns_false_marks_failed(self, db_session):
        """Book marked FAILED when import_epub returns False."""
        book = create_test_book(db_session, title="Corrupt File", status=BookStatus.IMPORTING)
        download = Download(
            book_id=book.id,
            torrent_hash="corrupt123456789ab0",
            torrent_name="Corrupt.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/torrent/corrupt",
            size=100,
            seeders=1,
            status=DownloadStatus.COMPLETED,
            file_path="/tmp/corrupt.epub",
        )
        db_session.add(download)
        db_session.commit()
        book_id = book.id

        mock_import = MagicMock()
        mock_import.import_epub.return_value = False

        pipeline = make_pipeline(db_session, import_service=mock_import)
        pipeline.run_pipeline()

        assert refresh_book(db_session, book_id).status == BookStatus.FAILED


class TestHardcoverSyncIntegration:
    def test_skips_existing_books_by_hardcover_id(self, db_session):
        """Existing books by hardcover_id are skipped; new ones are created."""
        existing = create_test_book(db_session, title="Existing Book", author_name="Author One")
        existing.hardcover_id = "12345"  # pyright: ignore[reportAttributeAccessIssue]
        db_session.commit()

        mock_hc = MagicMock()
        mock_hc.get_books_by_status.return_value = [
            {
                "hardcover_id": 12345,
                "title": "Existing Book",
                "authors": ["Author One"],
                "author_string": "Author One",
                "isbns": [],
                "cover_url": None,
                "series_name": None,
                "series_position": None,
                "status_id": 1,
            },
            {
                "hardcover_id": 99999,
                "title": "New Book",
                "authors": ["Author Two"],
                "author_string": "Author Two",
                "isbns": ["978-1234567890"],
                "cover_url": None,
                "series_name": None,
                "series_position": None,
                "status_id": 1,
            },
        ]

        config = {"pipeline": {"status_actions": {"want_to_read": {"download": True}}}}
        service = HardcoverSyncService(hardcover_client=mock_hc, config=config)
        result = service.sync_hardcover_lists(db_session)

        assert result["existing_skipped"] == 1
        assert result["new_books"] == 1
        assert result["errors"] == 0

        new_book = db_session.query(Book).filter(Book.hardcover_id == "99999").first()
        assert new_book is not None
        assert new_book.title == "New Book"
        assert new_book.status == BookStatus.MISSING
        assert new_book.isbn == "978-1234567890"

    def test_sync_then_pipeline_processes_new_books(self, db_session):
        """Books from Hardcover sync are picked up and processed by the pipeline."""
        mock_hc = MagicMock()
        mock_hc.get_books_by_status.return_value = [
            {
                "hardcover_id": 77777,
                "title": "Synced Book",
                "authors": ["Synced Author"],
                "author_string": "Synced Author",
                "isbns": [],
                "cover_url": None,
                "series_name": None,
                "series_position": None,
                "status_id": 1,
            },
        ]

        config = {"pipeline": {"status_actions": {"want_to_read": {"download": True}}}}
        sync_service = HardcoverSyncService(hardcover_client=mock_hc, config=config)
        sync_service.sync_hardcover_lists(db_session)

        synced = db_session.query(Book).filter(Book.hardcover_id == "77777").first()
        assert synced is not None
        assert synced.status == BookStatus.MISSING
        synced_id = synced.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(guid="synced-guid")]

        mock_dl = MagicMock()
        mock_dl.add_torrent.return_value = True
        mock_dl.get_completed_file_path.return_value = "/tmp/Synced.epub"

        mock_import = MagicMock()
        mock_import.import_epub.return_value = True

        pipeline = make_pipeline(db_session, mock_search, mock_dl, mock_import)
        pipeline.run_pipeline()

        assert refresh_book(db_session, synced_id).status == BookStatus.IN_LIBRARY


class TestMultiBookPipeline:
    def test_books_at_different_stages_all_progress(self, db_session):
        """Multiple books at WANTED, GRABBED, DOWNLOADING all advance in one run."""
        book_a = create_test_book(db_session, title="Book A (Wanted)")

        book_b = create_test_book(db_session, title="Book B (Grabbed)", status=BookStatus.GRABBED)
        dl_b = Download(
            book_id=book_b.id,
            torrent_hash="grabbedbb12345678a0",
            torrent_name="BookB.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/b",
            size=2_000_000,
            seeders=20,
            status=DownloadStatus.QUEUED,
        )
        db_session.add(dl_b)

        book_c = create_test_book(db_session, title="Book C (Downloading)", status=BookStatus.DOWNLOADING)
        dl_c = Download(
            book_id=book_c.id,
            torrent_hash="downloadcc1234567a0",
            torrent_name="BookC.epub",
            indexer_name="TestIndexer",
            download_url="https://example.com/c",
            size=3_000_000,
            seeders=30,
            status=DownloadStatus.DOWNLOADING,
        )
        db_session.add(dl_c)

        db_session.commit()
        id_a, id_b, id_c = book_a.id, book_b.id, book_c.id

        mock_search = MagicMock()
        mock_search.search_book.return_value = [make_search_result(guid="multi-a")]

        mock_download = MagicMock()
        mock_download.add_torrent.return_value = True
        mock_download.get_completed_file_path.return_value = "/tmp/completed.epub"

        mock_import = MagicMock()
        mock_import.import_epub.return_value = True

        pipeline = make_pipeline(db_session, mock_search, mock_download, mock_import)
        pipeline.run_pipeline()

        final_a = refresh_book(db_session, id_a)
        final_b = refresh_book(db_session, id_b)
        final_c = refresh_book(db_session, id_c)

        assert final_a.status != BookStatus.WANTED
        assert final_b.status not in (BookStatus.WANTED, BookStatus.GRABBED)
        assert final_c.status == BookStatus.IN_LIBRARY

    def test_failure_in_one_book_doesnt_block_others(self, db_session):
        """One book failing search doesn't prevent other books from progressing."""
        book_good = create_test_book(db_session, title="Good Book")
        book_bad = create_test_book(db_session, title="Bad Book")
        db_session.commit()
        id_good, id_bad = book_good.id, book_bad.id

        mock_search = MagicMock()
        mock_search.search_book.side_effect = [
            RuntimeError("Search API error"),
            [make_search_result(guid="good-guid")],
        ]

        pipeline = make_pipeline(db_session, search_service=mock_search)
        pipeline.run_pipeline()

        statuses = {
            refresh_book(db_session, id_good).status,
            refresh_book(db_session, id_bad).status,
        }
        assert BookStatus.GRABBED in statuses
        assert BookStatus.FAILED in statuses
