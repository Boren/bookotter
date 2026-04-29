# pyright: reportGeneralTypeIssues=false

from unittest.mock import MagicMock

from backend.models.book import Book, BookStatus
from backend.services.pipeline_service import PipelineService
from backend.services.pipeline_states import can_transition, transition_book
from tests.helpers import create_test_book


class TestMissingStateTransitions:
    def test_missing_to_searching(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.SEARCHING.value) is True
        assert book.status == BookStatus.SEARCHING.value

    def test_missing_to_failed(self, db_session):
        book = create_test_book(db_session, status=BookStatus.MISSING)

        assert transition_book(book, BookStatus.FAILED.value) is True
        assert book.status == BookStatus.FAILED.value

    def test_wanted_to_missing(self, db_session):
        assert can_transition(BookStatus.WANTED.value, BookStatus.MISSING.value) is True

    def test_failed_to_missing(self, db_session):
        assert can_transition(BookStatus.FAILED.value, BookStatus.MISSING.value) is True

    def test_missing_cannot_go_to_in_library(self, db_session):
        assert can_transition(BookStatus.MISSING.value, BookStatus.IN_LIBRARY.value) is False


class TestPipelinePicksUpMissing:
    def test_process_wanted_books_includes_missing(self, db_session):
        wanted = create_test_book(db_session, title="Wanted Book", status=BookStatus.WANTED)
        missing = create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
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
