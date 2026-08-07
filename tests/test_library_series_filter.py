"""Tests for the series filter and series_position sort on GET /api/library/books."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(db_session):
    """Three books in one series (messy casing/whitespace), one other series, one no series."""
    books = {
        "second": create_test_book(db_session, title="Caliban's War", series_name="The Expanse", series_position=2.0),
        "first": create_test_book(db_session, title="Leviathan Wakes", series_name="the expanse", series_position=1.0),
        "unpositioned": create_test_book(
            db_session, title="Expanse Novella", series_name="  The Expanse  ", series_position=None
        ),
        "other_series": create_test_book(
            db_session, title="The Fellowship", series_name="Lord of the Rings", series_position=1.0
        ),
        "no_series": create_test_book(db_session, title="Standalone Book"),
    }
    db_session.commit()
    return {key: book.id for key, book in books.items()}


class TestSeriesFilter:
    def test_series_filter_case_insensitive_and_trimmed(self, client, seeded):
        response = client.get("/api/library/books", params={"series": "the expanse"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        returned_ids = {b["id"] for b in data["books"]}
        assert seeded["other_series"] not in returned_ids
        assert seeded["no_series"] not in returned_ids

    def test_series_filter_trims_query_value(self, client, seeded):
        response = client.get("/api/library/books", params={"series": "  The Expanse  "})
        assert response.status_code == 200
        assert response.json()["total"] == 3

    def test_sort_by_series_position_nulls_last(self, client, seeded):
        response = client.get(
            "/api/library/books",
            params={"series": "The Expanse", "sort_by": "series_position", "sort_order": "asc"},
        )
        assert response.status_code == 200
        ids = [b["id"] for b in response.json()["books"]]
        assert ids == [seeded["first"], seeded["second"], seeded["unpositioned"]]

    def test_sort_by_series_position_accepted_without_filter(self, client, seeded):
        response = client.get("/api/library/books", params={"sort_by": "series_position"})
        assert response.status_code == 200

    def test_no_series_filter_returns_all(self, client, seeded):
        response = client.get("/api/library/books")
        assert response.status_code == 200
        assert response.json()["total"] == 5
