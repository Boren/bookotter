"""Tests for epub_meta_state bookkeeping in PUT /api/library/books/{id}."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.book import BookStatus, EpubMetaState, RootFolder
from tests.helpers import create_test_book, create_test_epub


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


def _library_book(db_session, tmp_path, *, with_valid_epub: bool):
    rf = RootFolder(name="Test", path=str(tmp_path), folder_organization="flat")
    db_session.add(rf)
    db_session.commit()
    book = create_test_book(
        db_session,
        title="Editable",
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=rf.id,
        file_path="Editable.epub",
    )
    book.epub_meta_state = EpubMetaState.SYNCED.value
    book.epub_meta_attempts = 2
    db_session.commit()
    epub_path = tmp_path / "Editable.epub"
    if with_valid_epub:
        create_test_epub(str(epub_path), "Editable", "Someone")
    else:
        epub_path.write_bytes(b"corrupt")
    return book


class TestUpdateBookMetaState:
    def test_successful_write_marks_synced(self, client, db_session, tmp_path):
        book = _library_book(db_session, tmp_path, with_valid_epub=True)

        resp = client.put(f"/api/library/books/{book.id}", json={"title": "Edited Title"})

        assert resp.status_code == 200
        db_session.refresh(book)
        assert book.epub_meta_state == EpubMetaState.SYNCED.value
        assert book.epub_meta_synced_at is not None
        assert book.epub_meta_attempts == 0

    def test_failed_write_resets_state_for_self_heal(self, client, db_session, tmp_path):
        book = _library_book(db_session, tmp_path, with_valid_epub=False)

        resp = client.put(f"/api/library/books/{book.id}", json={"title": "Edited Title"})

        assert resp.status_code == 200
        db_session.refresh(book)
        assert book.epub_meta_state is None
        assert book.epub_meta_attempts == 0
