import asyncio

from backend.api.routes.wanted import list_missing_books, search_all_missing
from backend.models.book import Book, BookStatus
from tests.helpers import create_test_book


class TestListMissingBooks:
    def test_returns_missing_books(self, db_session):
        create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
        db_session.commit()

        payload = asyncio.run(list_missing_books(db_session))

        assert payload["total"] == 1
        assert payload["books"][0]["title"] == "Missing Book"
        assert payload["books"][0]["status"] == BookStatus.MISSING.value

    def test_excludes_non_missing_books(self, db_session):
        create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
        create_test_book(db_session, title="Wanted Book", status=BookStatus.WANTED)
        create_test_book(db_session, title="Library Book", status=BookStatus.IN_LIBRARY)
        db_session.commit()

        payload = asyncio.run(list_missing_books(db_session))

        assert payload["total"] == 1
        assert [book["title"] for book in payload["books"]] == ["Missing Book"]


class TestSearchAllMissing:
    def test_triggers_search_for_all_missing(self, db_session):
        missing_one = create_test_book(db_session, title="Missing One", status=BookStatus.MISSING)
        missing_two = create_test_book(db_session, title="Missing Two", status=BookStatus.MISSING)
        create_test_book(db_session, title="Wanted Book", status=BookStatus.WANTED)
        db_session.commit()

        payload = asyncio.run(search_all_missing(db_session))

        assert payload["triggered"] == 2
        assert set(payload["book_ids"]) == {missing_one.id, missing_two.id}

        db_session.expire_all()
        statuses = {book.id: db_session.get(Book, book.id).status for book in [missing_one, missing_two]}
        assert statuses == {
            missing_one.id: BookStatus.SEARCHING.value,
            missing_two.id: BookStatus.SEARCHING.value,
        }

    def test_returns_triggered_count(self, db_session):
        create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
        db_session.commit()

        payload = asyncio.run(search_all_missing(db_session))

        assert payload["triggered"] == 1
