"""Tests for the ereader_delivery_status filter on GET /api/library/books."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.book import BookStatus, EreaderDeliveryStatus
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
    """One book per delivery state plus one never queued (NULL)."""
    by_status = {}
    for status in [s.value for s in EreaderDeliveryStatus] + [None]:
        book = create_test_book(
            db_session,
            title=f"Book {status or 'NONE'}",
            status=BookStatus.IN_LIBRARY.value,
        )
        book.ereader_delivery_status = status
        by_status[status or "NONE"] = book.id
    db_session.commit()
    return by_status


class TestEreaderDeliveryFilter:
    @pytest.mark.parametrize("status", [s.value for s in EreaderDeliveryStatus])
    def test_filter_by_each_status(self, client, seeded, status):
        response = client.get(f"/api/library/books?ereader_delivery_status={status}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["books"][0]["id"] == seeded[status]

    def test_filter_none_matches_never_queued(self, client, seeded):
        response = client.get("/api/library/books?ereader_delivery_status=NONE")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["books"][0]["id"] == seeded["NONE"]

    def test_no_filter_returns_all(self, client, seeded):
        response = client.get("/api/library/books")
        assert response.status_code == 200
        assert response.json()["total"] == len(seeded)

    def test_invalid_value_rejected(self, client, seeded):
        response = client.get("/api/library/books?ereader_delivery_status=bogus")
        assert response.status_code == 422
