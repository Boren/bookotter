# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""End-to-end test (T17): synthetic-failure → manual retry → success.

Seeds a book in FAILED state, hits POST /api/library/books/{id}/retry to drive
it back into the pipeline, then exercises the full post-retry pipeline cycle
with mocked external clients (Hardcover/Prowlarr/qBittorrent/cover fetch).

Asserts the book ends in IN_LIBRARY, failure_history preserves the original
failure plus the MANUAL_RETRY sentinel, the imported EPUB exists, has its
HTML description stripped, and has a cover embedded.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.errors import FailureReason
from backend.main import app
from backend.models import blocklist  # noqa: F401 — register tables
from backend.models.book import Author, Book, BookStatus, FolderOrganization, RootFolder
from backend.services.import_service import ImportService
from backend.services.pipeline_service import PipelineService
from backend.services.search_service import ScoredResult
from backend.utils.clock import naive_utcnow
from tests.helpers import create_test_epub

# Minimal valid JPEG header bytes — ebooklib stores image bytes verbatim
# without decoding. Same constant pattern as tests/test_cover_embed.py.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


@pytest.fixture
def db_session():
    """In-memory SQLite shared across pipeline-spawned sessions via StaticPool.

    The pipeline service creates fresh sessions via session_factory; without
    StaticPool each new session would see an independent empty database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    session.session_factory = SessionLocal
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_search_result() -> ScoredResult:
    """A ScoredResult that survives _search_and_grab → grab_known_result.

    The magnet URL must contain a valid 40-char hex info hash so
    extract_info_hash_from_url returns truthy; otherwise the pipeline will
    bounce the book back to WANTED instead of GRABBED.
    """
    return ScoredResult(
        guid="failure-recover-guid",
        indexer_id=1,
        indexer="TestIndexer",
        title="Dune [EPUB]",
        size=2_000_000,
        seeders=10,
        leechers=2,
        download_url="https://example.com/torrent",
        magnet_url="magnet:?xt=urn:btih:0000000000000000000000000000000000000017",
        publish_date="2026-01-01T00:00:00Z",
        protocol="torrent",
        approved=True,
    )


def _has_cover_meta(epub_book: epub.EpubBook) -> bool:
    """Match ImportService._has_existing_cover semantics — checks any namespace
    for a `<meta name="cover">` entry, since ebooklib's set_cover stores it
    under the None namespace."""
    for ns_metadata in epub_book.metadata.values():
        for _value, attrs in ns_metadata.get("meta", []):
            if attrs.get("name") == "cover":
                return True
    return False


class TestE2EFailureRetrySuccess:
    def test_synthetic_failure_to_recovery_via_manual_retry(self, client, db_session, tmp_path):
        lib_root = tmp_path / "library"
        lib_root.mkdir()
        rf = RootFolder(
            name="Test Library",
            path=str(lib_root),
            folder_organization=FolderOrganization.FLAT.value,
            created_at=naive_utcnow(),
        )
        db_session.add(rf)
        db_session.flush()

        author = Author(name="Frank Herbert", created_at=naive_utcnow())
        db_session.add(author)
        db_session.flush()

        book = Book(
            title="Dune",
            hardcover_id="test-dune",
            author_id=author.id,
            status=BookStatus.FAILED.value,
            failure_reason=FailureReason.PROWLARR_UNREACHABLE.value,
            retry_count=1,
            failure_history=[],
            cover_url="https://example.com/cover.jpg",
            description="<p>Pre-existing description</p>",
            root_folder_id=rf.id,
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
        )
        db_session.add(book)
        db_session.commit()
        book_id = book.id

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        fixture_epub = download_dir / "Dune.epub"
        create_test_epub(str(fixture_epub), title="Dune", author="Frank Herbert")

        start = time.monotonic()

        response = client.post(f"/api/library/books/{book_id}/retry")
        assert response.status_code == 202

        db_session.expire_all()
        book = db_session.get(Book, book_id)
        assert book is not None
        assert book.status == BookStatus.WANTED.value
        assert book.retry_count == 0
        assert book.failure_reason is None
        assert book.failure_history is not None
        assert len(book.failure_history) == 2, (
            f"failure_history must contain original failure + MANUAL_RETRY, got: {book.failure_history}"
        )
        assert book.failure_history[0]["reason"] == FailureReason.PROWLARR_UNREACHABLE.value
        assert book.failure_history[1]["reason"] == "MANUAL_RETRY"

        mock_search_service = MagicMock()
        mock_search_service.search_book.return_value = [_make_search_result()]

        mock_download_service = MagicMock()
        mock_download_service.add_torrent.return_value = True
        mock_download_service.get_completed_file_path.return_value = str(fixture_epub)

        import_service = ImportService(db_session.session_factory())

        pipeline = PipelineService(
            search_service=mock_search_service,
            download_service=mock_download_service,
            import_service=import_service,
            db_session_factory=db_session.session_factory,
        )

        # Patch time.sleep to no-op so any defensive backoff/rate-limit sleeps
        # (e.g. download_service.POST_ADD_DELAY_SECONDS, hardcover retry delays,
        # backend.utils.retry.retry_with_backoff) cannot push past the 5s budget.
        # Also patch get_first_real_ereader to return None so E-reader delivery
        # (which tries a real SSH connection and times out after ~10s) is skipped.
        with (
            patch("time.sleep", lambda *a, **kw: None),
            patch(
                "backend.services.import_service.fetch_cover",
                return_value=(JPEG_BYTES, "image/jpeg"),
            ),
            patch("backend.clients.hardcover_client.HardcoverClient", MagicMock()),
            patch("backend.clients.prowlarr_client.ProwlarrClient", MagicMock()),
            patch("backend.clients.qbittorrent_client.QBittorrentClient", MagicMock()),
            patch("backend.config.get_first_real_ereader", return_value=None),
        ):
            grabbed = pipeline.process_wanted_books()
            assert grabbed == 1
            db_session.expire_all()
            assert db_session.get(Book, book_id).status == BookStatus.GRABBED.value

            results = pipeline.run_pipeline(holder="manual")

        assert results.get("grabbed", 0) == 1
        assert results.get("downloading", 0) == 1
        assert results.get("importing", 0) == 1

        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"E2E recovery flow took {elapsed:.2f}s — must stay under 5s"

        db_session.expire_all()
        book = db_session.get(Book, book_id)
        assert book is not None
        assert book.status == BookStatus.IN_LIBRARY.value, (
            f"Expected status=in_library after recovery, got {book.status!r}"
        )

        assert book.failure_history is not None
        reasons = [entry["reason"] for entry in book.failure_history]
        assert FailureReason.PROWLARR_UNREACHABLE.value in reasons, (
            f"Original failure must be preserved, got: {reasons}"
        )
        assert "MANUAL_RETRY" in reasons, f"MANUAL_RETRY must be preserved, got: {reasons}"

        assert book.file_path is not None, "file_path must be set after import"
        epub_path = Path(str(rf.path)) / str(book.file_path)
        assert epub_path.exists(), f"Expected EPUB at {epub_path}"

        book_epub = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        descriptions = book_epub.get_metadata("DC", "description")
        assert descriptions, "EPUB description metadata missing"
        desc_text = descriptions[0][0]
        assert "<p>" not in desc_text and "</p>" not in desc_text, (
            f"Expected HTML-stripped description, found tags in: {desc_text!r}"
        )
        assert desc_text.strip() == "Pre-existing description", (
            f"Expected 'Pre-existing description', got {desc_text!r}"
        )

        cover_image_items = [item for item in book_epub.get_items() if isinstance(item, epub.EpubCover)]
        assert _has_cover_meta(book_epub) or cover_image_items, (
            "EPUB must have an embedded cover (cover meta or EpubCover item)"
        )
