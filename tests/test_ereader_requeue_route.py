"""Tests for POST /api/library/books/{id}/ereader-requeue and ereader stats."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.book import BookStatus, EreaderDeliveryStatus, RootFolder
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
    book.ereader_delivery_status = delivery_status
    book.ereader_delivery_attempts = 3
    db_session.commit()
    return book


class TestEreaderRequeue:
    @pytest.mark.parametrize(
        "status", [EreaderDeliveryStatus.SKIPPED.value, EreaderDeliveryStatus.DELIVERED.value, None]
    )
    def test_requeue_from_queueable_states(self, client, db_session, status):
        book = _make_library_book(db_session, status)

        response = client.post(f"/api/library/books/{book.id}/ereader-requeue")

        assert response.status_code == 202
        data = response.json()
        assert data["previous_status"] == status
        assert data["new_status"] == EreaderDeliveryStatus.PENDING.value
        assert data["already_queued"] is False
        # TestClient runs without lifespan, so app.state.pipeline is absent
        assert data["kicked"] is False

        db_session.refresh(book)
        assert book.ereader_delivery_status == EreaderDeliveryStatus.PENDING.value
        assert book.ereader_delivery_attempts == 0
        assert book.ereader_first_pending_at is not None
        # Manual send pins the book so mirror cleanup keeps it on the device
        assert book.ereader_pinned is True

    def test_requeue_pending_is_idempotent(self, client, db_session):
        book = _make_library_book(db_session, EreaderDeliveryStatus.PENDING.value)

        response = client.post(f"/api/library/books/{book.id}/ereader-requeue")

        assert response.status_code == 202
        data = response.json()
        assert data["already_queued"] is True
        assert data["new_status"] == EreaderDeliveryStatus.PENDING.value

        db_session.refresh(book)
        # Idempotent: no state was touched (attempts stay at the fixture's 3)
        assert book.ereader_delivery_attempts == 3

    def test_requeue_rejected_while_in_progress(self, client, db_session):
        book = _make_library_book(db_session, EreaderDeliveryStatus.IN_PROGRESS.value)
        response = client.post(f"/api/library/books/{book.id}/ereader-requeue")
        assert response.status_code == 409

    def test_requeue_kicks_pipeline_when_available(self, client, db_session):
        from unittest.mock import MagicMock

        book = _make_library_book(db_session, None)
        pipeline = MagicMock()
        app.state.pipeline = pipeline
        try:
            response = client.post(f"/api/library/books/{book.id}/ereader-requeue")
        finally:
            del app.state.pipeline

        assert response.status_code == 202
        assert response.json()["kicked"] is True
        # BackgroundTasks run before TestClient returns
        pipeline.kick_ereader_delivery.assert_called_once()

    def test_requeue_rejected_without_file(self, client, db_session):
        book = _make_library_book(db_session, EreaderDeliveryStatus.SKIPPED.value, with_file=False)
        response = client.post(f"/api/library/books/{book.id}/ereader-requeue")
        assert response.status_code == 400
        assert "no library file" in response.json()["detail"]

    def test_requeue_unknown_book_404(self, client):
        response = client.post("/api/library/books/999999/ereader-requeue")
        assert response.status_code == 404


class TestEreaderUnpin:
    def test_unpin_clears_pin(self, client, db_session):
        book = _make_library_book(db_session, EreaderDeliveryStatus.DELIVERED.value)
        book.ereader_pinned = True
        db_session.commit()

        response = client.delete(f"/api/library/books/{book.id}/ereader-pin")

        assert response.status_code == 200
        data = response.json()
        assert data["was_pinned"] is True
        assert data["ereader_pinned"] is False
        db_session.refresh(book)
        assert book.ereader_pinned is False

    def test_unpin_unpinned_book_is_noop(self, client, db_session):
        book = _make_library_book(db_session, None)

        response = client.delete(f"/api/library/books/{book.id}/ereader-pin")

        assert response.status_code == 200
        assert response.json()["was_pinned"] is False

    def test_unpin_unknown_book_404(self, client):
        response = client.delete("/api/library/books/999999/ereader-pin")
        assert response.status_code == 404


class TestEreaderStats:
    def test_stats_include_ereader_delivery_counts(self, client, db_session):
        _make_library_book(db_session, EreaderDeliveryStatus.PENDING.value, title="Stats One")
        _make_library_book(db_session, EreaderDeliveryStatus.PENDING.value, title="Stats Two")
        _make_library_book(db_session, EreaderDeliveryStatus.SKIPPED.value, title="Stats Three")
        _make_library_book(db_session, EreaderDeliveryStatus.DELIVERED.value, title="Stats Four")

        response = client.get("/api/library/stats")

        assert response.status_code == 200
        counts = response.json()["by_ereader_delivery_status"]
        assert counts["PENDING"] == 2
        assert counts["SKIPPED"] == 1
        assert counts["DELIVERED"] == 1
        assert counts["IN_PROGRESS"] == 0
