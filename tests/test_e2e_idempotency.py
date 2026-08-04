"""Idempotency E2E tests for repeated pipeline and sync runs."""

from unittest.mock import MagicMock

from backend.models.book import Book, BookStatus, Download
from backend.services.hardcover_sync_service import HardcoverSyncService
from backend.services.pipeline_service import PipelineService
from tests.helpers import create_test_book
from tests.test_integration import make_search_result


def _pipeline(db_session, *, search_service=None, download_service=None, import_service=None) -> PipelineService:
    return PipelineService(
        search_service=search_service,
        download_service=download_service,
        import_service=import_service,
        db_session_factory=lambda: db_session,
    )


class TestPipelineIdempotency:
    def test_second_full_cycle_is_no_op_for_completed_books(self, db_session):
        """A second full cycle does not re-search or create new downloads for imported books."""
        for i in range(1, 6):
            create_test_book(db_session, title=f"Book {i}", author_name=f"Author {i}")
        db_session.commit()

        mock_search = MagicMock()
        mock_search.search_book.side_effect = [
            [make_search_result(guid=f"book-{i}-guid", title=f"Book {i} [EPUB]")] for i in range(1, 6)
        ]

        mock_download = MagicMock()
        mock_download.add_torrent.return_value = True
        mock_download.get_completed_file_path.side_effect = [f"/tmp/book-{i}.epub" for i in range(1, 6)]

        def _import_side_effect(book, file_path):
            book.status = BookStatus.IN_LIBRARY.value
            db_session.commit()
            return True

        mock_import = MagicMock()
        mock_import.import_epub.side_effect = _import_side_effect

        pipeline = _pipeline(
            db_session,
            search_service=mock_search,
            download_service=mock_download,
            import_service=mock_import,
        )

        first_grabbed = pipeline.process_wanted_books()
        first_results = pipeline.run_pipeline(holder="manual")

        db_session.expire_all()
        all_books = db_session.query(Book).order_by(Book.id).all()
        assert len(all_books) == 5
        assert all(book.status == BookStatus.IN_LIBRARY.value for book in all_books)
        assert first_grabbed == 5
        assert first_results["grabbed"] == 5
        assert first_results["downloading"] == 5
        assert first_results["importing"] == 5

        book_count_before = db_session.query(Book).count()
        download_count_before = db_session.query(Download).count()

        mock_search.reset_mock()
        mock_download.reset_mock()
        mock_import.reset_mock()

        second_grabbed = pipeline.process_wanted_books()
        second_results = pipeline.run_pipeline(holder="manual")

        assert second_grabbed == 0
        assert second_results == {
            "failed_retried": 0,
            "grabbed": 0,
            "downloading": 0,
            "importing": 0,
            "kindle_delivery": 0,
        }
        mock_search.search_book.assert_not_called()
        mock_download.add_torrent.assert_not_called()
        mock_download.get_completed_file_path.assert_not_called()
        mock_import.import_epub.assert_not_called()

        db_session.expire_all()
        assert db_session.query(Book).count() == book_count_before
        assert db_session.query(Download).count() == download_count_before
        assert all(book.status == BookStatus.IN_LIBRARY.value for book in db_session.query(Book).all())

    def test_hardcover_sync_is_idempotent_for_same_payload(self, db_session, test_config):
        """Repeated Hardcover sync with the same books creates no duplicates."""
        hardcover_client = MagicMock()
        hardcover_client.get_books_by_status.return_value = [
            {
                "hardcover_id": 1001,
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "author_string": "Frank Herbert",
                "isbns": ["9780441013593"],
                "cover_url": None,
                "series_name": None,
                "series_position": None,
                "status_id": 1,
            },
            {
                "hardcover_id": 1002,
                "title": "Foundation",
                "authors": ["Isaac Asimov"],
                "author_string": "Isaac Asimov",
                "isbns": ["9780553293357"],
                "cover_url": None,
                "series_name": None,
                "series_position": None,
                "status_id": 1,
            },
        ]

        service = HardcoverSyncService(hardcover_client=hardcover_client, config=test_config)

        first = service.sync_hardcover_lists(db_session)
        second = service.sync_hardcover_lists(db_session)

        assert first == {"new_books": 2, "new_book_ids": [1, 2], "existing_skipped": 0, "errors": 0}
        assert second == {"new_books": 0, "new_book_ids": [], "existing_skipped": 2, "errors": 0}
        assert db_session.query(Book).count() == 2
