# pyright: reportGeneralTypeIssues=false

from unittest.mock import MagicMock

from backend.models.book import Book, BookStatus
from backend.services.pipeline_service import PipelineService
from backend.services.pipeline_states import can_transition, transition_book
from tests.helpers import create_test_book


class TestMissingStateTransitions:
    def test_missing_to_searching(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.SEARCHING.value, db_session) is True
        assert book.status == BookStatus.SEARCHING.value

    def test_missing_to_failed(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.FAILED.value, db_session) is True
        assert book.status == BookStatus.FAILED.value

    def test_wanted_to_missing(self, db_session):
        assert can_transition(BookStatus.WANTED.value, BookStatus.MISSING.value) is True

    def test_failed_to_missing(self, db_session):
        assert can_transition(BookStatus.FAILED.value, BookStatus.MISSING.value) is True

    def test_missing_cannot_go_to_in_library(self, db_session):
        assert can_transition(BookStatus.MISSING.value, BookStatus.IN_LIBRARY.value) is False


class TestPermanentFailedTransitions:
    def test_permanent_failed_only_from_failed(self, db_session):
        """PERMANENT_FAILED can only be reached from FAILED."""
        # WANTED → PERMANENT_FAILED must be invalid
        assert can_transition(BookStatus.WANTED.value, BookStatus.PERMANENT_FAILED.value) is False
        # SEARCHING → PERMANENT_FAILED must be invalid
        assert can_transition(BookStatus.SEARCHING.value, BookStatus.PERMANENT_FAILED.value) is False
        # FAILED → PERMANENT_FAILED must be valid
        assert can_transition(BookStatus.FAILED.value, BookStatus.PERMANENT_FAILED.value) is True

    def test_permanent_failed_to_wanted_only(self, db_session):
        """PERMANENT_FAILED can only transition to WANTED (force-retry)."""
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.WANTED.value) is True
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.SEARCHING.value) is False
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.MISSING.value) is False
        assert can_transition(BookStatus.PERMANENT_FAILED.value, BookStatus.FAILED.value) is False

    def test_permanent_failed_transition_book(self, db_session):
        """transition_book correctly moves FAILED → PERMANENT_FAILED."""
        book = create_test_book(db_session, status=BookStatus.FAILED)
        assert transition_book(book, BookStatus.PERMANENT_FAILED.value, db_session) is True
        assert book.status == BookStatus.PERMANENT_FAILED.value

    def test_transition_book_returns_false_after_concurrent_status_change(self, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED)
        mock_result = MagicMock(rowcount=0)
        db_session.execute = MagicMock(return_value=mock_result)

        assert transition_book(book, BookStatus.PERMANENT_FAILED.value, db_session) is False
        assert book.status == BookStatus.FAILED.value


class TestPipelinePicksUpMissing:
    def test_process_wanted_books_includes_missing(self, db_session):
        wanted = create_test_book(db_session, title="Wanted Book", author_name="Author One", status=BookStatus.WANTED)
        missing = create_test_book(
            db_session, title="Missing Book", author_name="Author Two", status=BookStatus.MISSING
        )
        db_session.commit()
        wanted_id = wanted.id
        missing_id = missing.id

        search_service = MagicMock()
        search_service.search_book.side_effect = [
            [
                {
                    "guid": "wanted-guid",
                    "title": "Wanted.epub",
                    "indexer": "TestIndexer",
                    "seeders": 10,
                    "size": 1024,
                    "download_url": "https://example.com/wanted",
                    "magnet_url": "magnet:?xt=urn:btih:aaaaaaaaaa1111111111aaaaaaaaaa1111111111&dn=Wanted",
                }
            ],
            [
                {
                    "guid": "missing-guid",
                    "title": "Missing.epub",
                    "indexer": "TestIndexer",
                    "seeders": 12,
                    "size": 2048,
                    "download_url": "https://example.com/missing",
                    "magnet_url": "magnet:?xt=urn:btih:bbbbbbbbbb2222222222bbbbbbbbbb2222222222&dn=Missing",
                }
            ],
        ]

        service = PipelineService(search_service=search_service, db_session_factory=lambda: db_session)

        assert service.process_wanted_books() == 2

        db_session.expire_all()
        assert db_session.get(Book, wanted_id).status == BookStatus.GRABBED
        assert db_session.get(Book, missing_id).status == BookStatus.GRABBED
