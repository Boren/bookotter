"""Tests for force-retry endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.errors import FailureReason
from backend.main import app
from backend.models import blocklist  # noqa: F401
from backend.models.book import BookStatus
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


class TestForceRetry:
    def test_retry_failed_book_returns_202(self, client, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED.value)
        book.failure_reason = FailureReason.DOWNLOAD_STALLED.value
        book.retry_count = 2
        db_session.commit()

        response = client.post(f"/api/library/books/{book.id}/retry")

        assert response.status_code == 202
        data = response.json()
        assert data["new_status"] == BookStatus.WANTED.value
        assert data["previous_status"] == BookStatus.FAILED.value
        assert data["book_id"] == book.id

        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 0
        assert book.failure_reason is None

    def test_retry_permanent_failed_book(self, client, db_session):
        book = create_test_book(db_session, status=BookStatus.PERMANENT_FAILED.value)
        book.failure_reason = FailureReason.RETRY_BUDGET_EXHAUSTED.value
        db_session.commit()

        response = client.post(f"/api/library/books/{book.id}/retry")

        assert response.status_code == 202
        data = response.json()
        assert data["previous_status"] == BookStatus.PERMANENT_FAILED.value
        assert data["new_status"] == BookStatus.WANTED.value

        db_session.refresh(book)
        assert book.status == BookStatus.WANTED.value
        assert book.failure_reason is None

    def test_retry_in_library_book_returns_400(self, client, db_session):
        book = create_test_book(db_session, status=BookStatus.IN_LIBRARY.value)
        db_session.commit()

        response = client.post(f"/api/library/books/{book.id}/retry")

        assert response.status_code == 400
        assert "not in a retryable state" in response.json()["detail"]

        db_session.refresh(book)
        assert book.status == BookStatus.IN_LIBRARY.value

    def test_retry_nonexistent_book_returns_404(self, client):
        response = client.post("/api/library/books/99999/retry")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_retry_resets_low_confidence(self, client, db_session):
        book = create_test_book(db_session, status=BookStatus.FAILED.value)
        book.low_confidence = True
        db_session.commit()

        response = client.post(f"/api/library/books/{book.id}/retry")

        assert response.status_code == 202
        db_session.refresh(book)
        assert book.low_confidence is False
