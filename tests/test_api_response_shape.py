"""Tests for API response shape including new fields."""

import pytest
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.main import app
from backend.models.book import BookStatus
from tests.helpers import create_test_book


@pytest.fixture
def client(db_session):
    """Create a test client with overridden database dependency."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestApiResponseShape:
    """Test that API responses include all required fields."""

    def test_book_response_includes_new_fields(self, client, db_session):
        """Verify that book responses include the new fields."""
        book = create_test_book(db_session, status=BookStatus.WANTED.value)
        db_session.commit()

        response = client.get(f"/api/library/books/{book.id}")

        assert response.status_code == 200
        data = response.json()
        assert "failure_reason" in data
        assert "retry_count" in data
        assert "low_confidence" in data
        assert "ereader_delivery_status" in data
        assert "ereader_delivery_attempts" in data

    def test_failure_reason_null_for_successful_books(self, client, db_session):
        """Verify that failure_reason is null for books in IN_LIBRARY status."""
        book = create_test_book(db_session, status=BookStatus.IN_LIBRARY.value)
        db_session.commit()

        response = client.get(f"/api/library/books/{book.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["failure_reason"] is None

    def test_low_confidence_false_by_default(self, client, db_session):
        """Verify that low_confidence defaults to False."""
        book = create_test_book(db_session, status=BookStatus.WANTED.value)
        db_session.commit()

        response = client.get(f"/api/library/books/{book.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["low_confidence"] is False
