"""Tests for GET /api/library/books/{id}/download."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.book import BookStatus, RootFolder
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


def _make_book_with_file(db_session, tmp_path, file_path="Download Book.epub", write_file=True):
    rf = RootFolder(name="Test", path=str(tmp_path), folder_organization="flat")
    db_session.add(rf)
    db_session.commit()
    if write_file:
        epub = tmp_path / file_path
        epub.write_bytes(b"fake epub bytes")
    book = create_test_book(
        db_session,
        title="Download Book",
        status=BookStatus.IN_LIBRARY.value,
        root_folder_id=rf.id,
        file_path=file_path,
    )
    db_session.commit()
    return book


class TestBookDownload:
    def test_download_serves_epub(self, client, db_session, tmp_path):
        book = _make_book_with_file(db_session, tmp_path)

        response = client.get(f"/api/library/books/{book.id}/download")

        assert response.status_code == 200
        assert response.content == b"fake epub bytes"
        assert response.headers["content-type"] == "application/epub+zip"
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        # Starlette RFC 5987-encodes filenames containing spaces
        assert "Download%20Book.epub" in disposition

    def test_download_unknown_book_404(self, client):
        response = client.get("/api/library/books/999999/download")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_download_book_without_file_404(self, client, db_session):
        book = create_test_book(db_session, title="No File Book")
        db_session.commit()

        response = client.get(f"/api/library/books/{book.id}/download")

        assert response.status_code == 404
        assert "no library file" in response.json()["detail"]

    def test_download_file_missing_on_disk_404(self, client, db_session, tmp_path):
        book = _make_book_with_file(db_session, tmp_path, write_file=False)

        response = client.get(f"/api/library/books/{book.id}/download")

        assert response.status_code == 404
        assert "file not found" in response.json()["detail"]

    def test_download_traversal_path_404(self, client, db_session, tmp_path):
        outside = tmp_path / "outside-root.txt"
        outside.write_text("secret")
        root = tmp_path / "library"
        root.mkdir()
        book = _make_book_with_file(db_session, root, file_path="../outside-root.txt", write_file=False)

        response = client.get(f"/api/library/books/{book.id}/download")

        assert response.status_code == 404
