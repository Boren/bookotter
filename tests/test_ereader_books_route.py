"""Tests for GET /api/ereaders/{id}/books (on-device listing matched to library books)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api.routes.ereaders as ereaders_routes
from backend.clients.ereader_client import EreaderClient
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


def _ereader_config():
    return {
        "id": "abc12345",
        "name": "Test E-reader",
        "hostname": "ereader.local",
        "port": 22,
        "username": "root",
        "password": "",
        "ssh_key_path": "",
        "destination_path": "/mnt/us/books/",
    }


def _device_files():
    return [
        {"name": "matched-book.epub", "size": 1000, "modified": "2026-08-01T00:00:00+00:00"},
        {"name": "sideload.epub", "size": 2000, "modified": None},
    ]


class TestListEreaderBooksRoute:
    def test_unknown_ereader_404(self, client):
        with patch.object(ereaders_routes, "get_ereader_by_id", return_value=None):
            response = client.get("/api/ereaders/nope/books")
        assert response.status_code == 404

    def test_matched_file_gets_book_id_and_title(self, client, db_session):
        book = create_test_book(db_session, title="Matched Book", file_path="Author Name/matched-book.epub")
        # A book with no file yet must not break the basename join
        create_test_book(db_session, title="Wanted Only", file_path=None)
        db_session.commit()

        with (
            patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config()),
            patch.object(ereaders_routes.EreaderClient, "list_books", return_value=_device_files()),
        ):
            response = client.get("/api/ereaders/abc12345/books")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2

        matched, unmatched = data["books"]
        assert matched["book_id"] == book.id
        assert matched["title"] == "Matched Book"
        assert unmatched["book_id"] is None
        assert unmatched["title"] is None

    def test_listing_failure_keeps_error_envelope(self, client):
        with (
            patch.object(ereaders_routes, "get_ereader_by_id", return_value=_ereader_config()),
            patch.object(ereaders_routes.EreaderClient, "list_books", side_effect=RuntimeError("offline")),
        ):
            response = client.get("/api/ereaders/abc12345/books")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["books"] == []


class TestListBooksModifiedTimestamp:
    def _entry(self, filename: str, st_size: int = 100, st_mtime: int | None = 1_700_000_000):
        return SimpleNamespace(filename=filename, st_size=st_size, st_mtime=st_mtime)

    def _client_with_entries(self, entries):
        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")
        sftp = MagicMock()
        sftp.listdir_attr.return_value = entries
        ssh = MagicMock()
        ssh.open_sftp.return_value = sftp
        return client, ssh

    def test_modified_is_iso_utc_string(self):
        client, ssh = self._client_with_entries(
            [self._entry("book.epub", st_mtime=1_700_000_000), self._entry("notes.txt")]
        )
        with patch.object(client, "_create_ssh_client", return_value=ssh):
            files = client.list_books()

        assert [f["name"] for f in files] == ["book.epub"]
        assert files[0]["modified"] == "2023-11-14T22:13:20+00:00"

    def test_missing_mtime_yields_none(self):
        client, ssh = self._client_with_entries([self._entry("book.epub", st_mtime=None)])
        with patch.object(client, "_create_ssh_client", return_value=ssh):
            files = client.list_books()

        assert files[0]["modified"] is None
