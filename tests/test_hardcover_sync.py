# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false, reportArgumentType=false

"""Tests for HardcoverSyncService dedup and race-safe author creation."""

import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Author, Book
from backend.services.hardcover_sync_service import (
    HardcoverSyncService,
    _get_or_create_author,
)


@pytest.fixture
def shared_db_factory():
    """File-based SQLite session factory shared across threads (for race tests)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(bind=engine)
        SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        yield SessionFactory
        engine.dispose()


def _make_hc_book(
    hardcover_id: str | int | None = "hc-1",
    title: str = "Dune",
    isbn: str | None = "978-0-441-17271-9",
    authors: list[str] | None = None,
    description: str | None = None,
    status_id: int = 1,
) -> dict:
    return {
        "hardcover_id": hardcover_id if hardcover_id is not None else "",
        "title": title,
        "isbns": [isbn] if isbn else [],
        "authors": authors if authors is not None else ["Frank Herbert"],
        "cover_url": None,
        "series_name": None,
        "series_position": None,
        "description": description,
        "status_id": status_id,
    }


def _make_service(hc_books: list[dict], config: dict | None = None) -> HardcoverSyncService:
    mock_client = MagicMock()
    mock_client.get_books_by_status.return_value = hc_books
    cfg = config or {"sync": {"include_statuses": {"want_to_read": True}}}
    return HardcoverSyncService(hardcover_client=mock_client, config=cfg)


class TestDedup:
    def test_same_hardcover_id_is_deduplicated(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-42", title="Dune")])
        result1 = svc.sync_hardcover_lists(db_session)
        assert result1["new_books"] == 1
        assert result1["existing_skipped"] == 0

        svc2 = _make_service([_make_hc_book(hardcover_id="hc-42", title="Dune")])
        result2 = svc2.sync_hardcover_lists(db_session)
        assert result2["new_books"] == 0
        assert result2["existing_skipped"] == 1

        assert db_session.query(Book).count() == 1

    def test_same_isbn_dedup_when_no_hardcover_id_match(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-1", isbn="978-1-111-11111-1")])
        result1 = svc.sync_hardcover_lists(db_session)
        assert result1["new_books"] == 1

        svc2 = _make_service([_make_hc_book(hardcover_id="hc-2", isbn="978-1-111-11111-1")])
        result2 = svc2.sync_hardcover_lists(db_session)
        assert result2["new_books"] == 0
        assert result2["existing_skipped"] == 1

        assert db_session.query(Book).count() == 1

    def test_isbn_dedup_when_new_book_has_no_hardcover_id(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-1", isbn="978-2-222-22222-2")])
        svc.sync_hardcover_lists(db_session)

        svc2 = _make_service([_make_hc_book(hardcover_id=None, isbn="978-2-222-22222-2")])
        result2 = svc2.sync_hardcover_lists(db_session)
        assert result2["new_books"] == 0
        assert result2["existing_skipped"] == 1

    def test_book_with_no_identifier_is_skipped_and_logged(self, db_session, caplog):
        svc = _make_service([_make_hc_book(hardcover_id=None, isbn=None, title="Mystery Book")])
        with caplog.at_level("WARNING"):
            result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 0
        assert result["errors"] == 1
        assert any("no identifier" in rec.message.lower() for rec in caplog.records)
        assert db_session.query(Book).count() == 0

    def test_different_hardcover_id_and_isbn_creates_new_book(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-1", isbn="978-3-333-33333-3")])
        svc.sync_hardcover_lists(db_session)

        svc2 = _make_service([_make_hc_book(hardcover_id="hc-2", isbn="978-4-444-44444-4")])
        result2 = svc2.sync_hardcover_lists(db_session)

        assert result2["new_books"] == 1
        assert db_session.query(Book).count() == 2

    def test_one_bad_book_does_not_kill_sync(self, db_session):
        books = [
            _make_hc_book(hardcover_id="hc-100", title="Good Book 1", isbn="978-5-555-55555-5"),
            _make_hc_book(hardcover_id=None, isbn=None, title="Bad Book"),
            _make_hc_book(hardcover_id="hc-101", title="Good Book 2", isbn="978-6-666-66666-6"),
        ]
        svc = _make_service(books)
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 2
        assert result["errors"] == 1
        assert db_session.query(Book).count() == 2

    def test_description_populated_from_hardcover_api(self, db_session):
        """When Hardcover API returns description, Book row has that description."""
        books = [
            _make_hc_book(
                hardcover_id="hc-desc-1",
                title="Epic Tale",
                isbn="978-7-777-77777-7",
                description="An epic tale of testing.",
            )
        ]
        svc = _make_service(books)
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 1
        book = db_session.query(Book).filter(Book.hardcover_id == "hc-desc-1").first()
        assert book is not None
        assert book.description == "An epic tale of testing."

    def test_description_null_when_hardcover_api_returns_null(self, db_session):
        """When Hardcover API returns description: null, Book row has description IS NULL."""
        books = [
            _make_hc_book(
                hardcover_id="hc-desc-2",
                title="Mystery Book",
                isbn="978-8-888-88888-8",
                description=None,
            )
        ]
        svc = _make_service(books)
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 1
        book = db_session.query(Book).filter(Book.hardcover_id == "hc-desc-2").first()
        assert book is not None
        assert book.description is None


class TestNewBookIds:
    def test_result_contains_ids_of_created_books(self, db_session):
        books = [
            _make_hc_book(hardcover_id="hc-201", title="Book A", isbn="978-9-999-99999-1"),
            _make_hc_book(hardcover_id="hc-202", title="Book B", isbn="978-9-999-99999-2"),
        ]
        svc = _make_service(books)
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 2
        created_ids = [b.id for b in db_session.query(Book).order_by(Book.id).all()]
        assert result["new_book_ids"] == created_ids

    def test_existing_books_not_in_new_book_ids(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-300", isbn="978-9-999-99999-3")])
        svc.sync_hardcover_lists(db_session)

        svc2 = _make_service(
            [
                _make_hc_book(hardcover_id="hc-300", isbn="978-9-999-99999-3"),
                _make_hc_book(hardcover_id="hc-301", title="New One", isbn="978-9-999-99999-4"),
            ]
        )
        result = svc2.sync_hardcover_lists(db_session)

        assert result["new_books"] == 1
        new_id = db_session.query(Book).filter(Book.hardcover_id == "hc-301").one().id
        assert result["new_book_ids"] == [new_id]

    def test_empty_when_no_statuses_enabled(self, db_session):
        config = {
            "sync": {
                "include_statuses": {
                    "currently_reading": False,
                    "want_to_read": False,
                    "read": False,
                }
            }
        }
        svc = _make_service([], config=config)
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_book_ids"] == []

    def test_empty_when_fetch_fails(self, db_session):
        svc = _make_service([])
        svc.hardcover_client.get_books_by_status.side_effect = RuntimeError("boom")
        result = svc.sync_hardcover_lists(db_session)

        assert result["errors"] == 1
        assert result["new_book_ids"] == []


class TestShelfStatusPersistence:
    def test_status_set_on_create(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-1", status_id=1)])
        svc.sync_hardcover_lists(db_session)

        book = db_session.query(Book).filter(Book.hardcover_id == "hc-shelf-1").one()
        assert book.hardcover_status == "want_to_read"

    def test_status_updated_when_book_moves_shelves(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-2", status_id=1)])
        svc.sync_hardcover_lists(db_session)

        svc2 = _make_service([_make_hc_book(hardcover_id="hc-shelf-2", status_id=3)])
        result = svc2.sync_hardcover_lists(db_session)

        book = db_session.query(Book).filter(Book.hardcover_id == "hc-shelf-2").one()
        assert book.hardcover_status == "read"
        assert result["new_books"] == 0

    def test_status_cleared_when_book_leaves_all_shelves(self, db_session):
        svc = _make_service(
            [
                _make_hc_book(hardcover_id="hc-shelf-3", status_id=1, isbn="978-1-000-00000-1"),
                _make_hc_book(hardcover_id="hc-shelf-4", title="Other", status_id=1, isbn="978-1-000-00000-2"),
            ]
        )
        svc.sync_hardcover_lists(db_session)

        # hc-shelf-3 disappears from every shelf; hc-shelf-4 remains
        svc2 = _make_service([_make_hc_book(hardcover_id="hc-shelf-4", title="Other", status_id=1)])
        svc2.sync_hardcover_lists(db_session)

        gone = db_session.query(Book).filter(Book.hardcover_id == "hc-shelf-3").one()
        kept = db_session.query(Book).filter(Book.hardcover_id == "hc-shelf-4").one()
        assert gone.hardcover_status is None
        assert kept.hardcover_status == "want_to_read"

    def test_status_not_cleared_when_api_returns_empty(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-5", status_id=1)])
        svc.sync_hardcover_lists(db_session)

        svc2 = _make_service([])
        svc2.sync_hardcover_lists(db_session)

        book = db_session.query(Book).filter(Book.hardcover_id == "hc-shelf-5").one()
        assert book.hardcover_status == "want_to_read"

    def test_all_shelves_fetched_regardless_of_include_statuses(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-6", status_id=1)])
        svc.sync_hardcover_lists(db_session)
        svc.hardcover_client.get_books_by_status.assert_called_once_with([1, 2, 3])

    def test_non_imported_shelf_updates_existing_without_creating(self, db_session):
        # Imported while on want_to_read...
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-7", status_id=1)])
        svc.sync_hardcover_lists(db_session)

        # ...then moved to read, which is NOT in include_statuses: status updates, no dupe
        svc2 = _make_service([_make_hc_book(hardcover_id="hc-shelf-7", status_id=3)])
        result = svc2.sync_hardcover_lists(db_session)

        assert result["new_books"] == 0
        assert db_session.query(Book).count() == 1
        assert db_session.query(Book).one().hardcover_status == "read"

    def test_new_book_on_non_imported_shelf_not_created(self, db_session):
        svc = _make_service([_make_hc_book(hardcover_id="hc-shelf-8", status_id=3)])
        result = svc.sync_hardcover_lists(db_session)

        assert result["new_books"] == 0
        assert db_session.query(Book).count() == 0


class TestGetOrCreateAuthor:
    def test_creates_author_when_missing(self, db_session):
        author = _get_or_create_author(db_session, "Frank Herbert")
        db_session.commit()

        assert author.id is not None
        assert author.name == "Frank Herbert"
        assert db_session.query(Author).count() == 1

    def test_returns_existing_author(self, db_session):
        first = _get_or_create_author(db_session, "Isaac Asimov")
        db_session.commit()

        second = _get_or_create_author(db_session, "Isaac Asimov")
        assert second.id == first.id
        assert db_session.query(Author).count() == 1

    def test_concurrent_create_no_dupes(self, shared_db_factory):
        """5 threads racing _get_or_create_author for same name → exactly 1 row."""
        results: list[int] = []
        errors: list[Exception] = []
        result_lock = threading.Lock()
        barrier = threading.Barrier(5)

        def create_author():
            db = shared_db_factory()
            try:
                barrier.wait()
                author = _get_or_create_author(db, "Frank Herbert")
                db.commit()
                with result_lock:
                    results.append(author.id)
            except Exception as e:
                with result_lock:
                    errors.append(e)
            finally:
                db.close()

        threads = [threading.Thread(target=create_author) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        assert len(set(results)) == 1, f"Expected 1 unique author id, got {set(results)}"

        verify_db = shared_db_factory()
        try:
            assert verify_db.query(Author).filter(Author.name == "Frank Herbert").count() == 1
        finally:
            verify_db.close()
