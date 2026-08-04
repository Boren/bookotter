"""Tests for POST /api/library/books/{id}/kindle-requeue and kindle stats."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.book import BookStatus, KindleDeliveryStatus, RootFolder
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


def _make_library_book(db_session, delivery_status: str | None, title: str = "Requeue Book", with_file: bool = True):
    rf = db_session.query(RootFolder).first()
    if rf is None:
        rf = RootFolder(name="Test", path="/library", folder_organization="flat")
        db_session.add(rf)
        db_session.commit()
    book = create_test_book(
        db_session,
        title=title,
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=rf.id if with_file else None,
        file_path=f"{title}.epub" if with_file else None,
    )
    book.kindle_delivery_status = delivery_status
    book.kindle_delivery_attempts = 3
    db_session.commit()
    return book


class TestKindleRequeue:
    @pytest.mark.parametrize("status", [KindleDeliveryStatus.SKIPPED.value, KindleDeliveryStatus.DELIVERED.value])
    def test_requeue_from_terminal_states(self, client, db_session, status):
        book = _make_library_book(db_session, status)

        response = client.post(f"/api/library/books/{book.id}/kindle-requeue")

        assert response.status_code == 202
        data = response.json()
        assert data["previous_status"] == status
        assert data["new_status"] == KindleDeliveryStatus.PENDING.value

        db_session.refresh(book)
        assert book.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert book.kindle_delivery_attempts == 0
        assert book.kindle_first_pending_at is not None

    @pytest.mark.parametrize("status", [KindleDeliveryStatus.PENDING.value, None])
    def test_requeue_rejected_for_non_terminal_states(self, client, db_session, status):
        book = _make_library_book(db_session, status)
        response = client.post(f"/api/library/books/{book.id}/kindle-requeue")
        assert response.status_code == 400

    def test_requeue_rejected_without_file(self, client, db_session):
        book = _make_library_book(db_session, KindleDeliveryStatus.SKIPPED.value, with_file=False)
        response = client.post(f"/api/library/books/{book.id}/kindle-requeue")
        assert response.status_code == 400
        assert "no library file" in response.json()["detail"]

    def test_requeue_unknown_book_404(self, client):
        response = client.post("/api/library/books/999999/kindle-requeue")
        assert response.status_code == 404


class TestKindleStats:
    def test_stats_include_kindle_delivery_counts(self, client, db_session):
        _make_library_book(db_session, KindleDeliveryStatus.PENDING.value, title="Stats One")
        _make_library_book(db_session, KindleDeliveryStatus.PENDING.value, title="Stats Two")
        _make_library_book(db_session, KindleDeliveryStatus.SKIPPED.value, title="Stats Three")
        _make_library_book(db_session, KindleDeliveryStatus.DELIVERED.value, title="Stats Four")

        response = client.get("/api/library/stats")

        assert response.status_code == 200
        counts = response.json()["by_kindle_delivery_status"]
        assert counts["PENDING"] == 2
        assert counts["SKIPPED"] == 1
        assert counts["DELIVERED"] == 1
        assert counts["IN_PROGRESS"] == 0
