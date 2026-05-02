"""Tests for scanner database schema and constraints."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.book import Book, BookStatus
from backend.models.scanner import (
    DismissedScanPath,
    MatchProposalStatus,
    ScanStatus,
)


@pytest.fixture
def schema_db():
    """Create an in-memory SQLite database with all models registered."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


class TestScannerTablesCreated:
    """Verify all scanner tables are created."""

    def test_scanner_tables_exist(self, schema_db):
        """Verify scans, match_proposals, and dismissed_scan_paths tables exist."""
        inspector = inspect(schema_db.get_bind())
        tables = inspector.get_table_names()

        assert "scans" in tables
        assert "match_proposals" in tables
        assert "dismissed_scan_paths" in tables

    def test_scan_columns(self, schema_db):
        """Verify Scan table has all required columns."""
        inspector = inspect(schema_db.get_bind())
        columns = {col["name"] for col in inspector.get_columns("scans")}

        required = {
            "id",
            "root_folder_id",
            "status",
            "started_at",
            "finished_at",
            "files_seen",
            "files_matched",
            "files_proposed",
            "files_unmatched",
            "files_failed",
            "error_message",
        }
        assert required.issubset(columns)

    def test_match_proposal_columns(self, schema_db):
        """Verify MatchProposal table has all required columns."""
        inspector = inspect(schema_db.get_bind())
        columns = {col["name"] for col in inspector.get_columns("match_proposals")}

        required = {
            "id",
            "scan_id",
            "root_folder_id",
            "relative_path",
            "file_size",
            "candidate_book_id",
            "match_method",
            "score",
            "status",
            "created_at",
            "decided_at",
        }
        assert required.issubset(columns)

    def test_dismissed_path_columns(self, schema_db):
        """Verify DismissedScanPath table has all required columns."""
        inspector = inspect(schema_db.get_bind())
        columns = {col["name"] for col in inspector.get_columns("dismissed_scan_paths")}

        required = {"id", "root_folder_id", "relative_path", "dismissed_at"}
        assert required.issubset(columns)


class TestDismissedPathUniqueConstraint:
    """Test dismissed_scan_paths unique constraint."""

    def test_dismissed_path_unique_constraint(self, schema_db):
        """Verify (root_folder_id, relative_path) is unique."""
        from backend.models.book import RootFolder

        root = RootFolder(name="Test Root", path="/test/root")
        schema_db.add(root)
        schema_db.flush()

        path1 = DismissedScanPath(root_folder_id=root.id, relative_path="book1.epub")
        schema_db.add(path1)
        schema_db.commit()

        path2 = DismissedScanPath(root_folder_id=root.id, relative_path="book1.epub")
        schema_db.add(path2)

        with pytest.raises(IntegrityError):
            schema_db.commit()

    def test_dismissed_path_same_path_different_root(self, schema_db):
        """Verify same path can exist in different root folders."""
        from backend.models.book import RootFolder

        root1 = RootFolder(name="Root 1", path="/root1")
        root2 = RootFolder(name="Root 2", path="/root2")
        schema_db.add_all([root1, root2])
        schema_db.flush()

        path1 = DismissedScanPath(root_folder_id=root1.id, relative_path="book.epub")
        path2 = DismissedScanPath(root_folder_id=root2.id, relative_path="book.epub")
        schema_db.add_all([path1, path2])
        schema_db.commit()

        assert path1.id is not None
        assert path2.id is not None


class TestBookConstraints:
    """Test Book model constraints."""

    def test_book_hardcover_id_not_null(self, schema_db):
        """Verify hardcover_id is NOT NULL."""
        book = Book(title="Test", hardcover_id=None, status=BookStatus.WANTED.value)
        schema_db.add(book)

        with pytest.raises(IntegrityError):
            schema_db.commit()

    def test_book_hardcover_id_unique(self, schema_db):
        """Verify hardcover_id is UNIQUE."""
        book1 = Book(title="Book 1", hardcover_id="hc-123", status=BookStatus.WANTED.value)
        book2 = Book(title="Book 2", hardcover_id="hc-123", status=BookStatus.WANTED.value)
        schema_db.add_all([book1, book2])

        with pytest.raises(IntegrityError):
            schema_db.flush()

    def test_book_source_column_exists(self, schema_db):
        """Verify source column exists and is nullable."""
        book = Book(title="Test", hardcover_id="hc-456", status=BookStatus.WANTED.value, source=None)
        schema_db.add(book)
        schema_db.commit()

        assert book.source is None

        book.source = "hardcover_sync"
        schema_db.commit()
        assert book.source == "hardcover_sync"

    def test_book_source_indexed(self, schema_db):
        """Verify source column is indexed."""
        inspector = inspect(schema_db.get_bind())
        indexes = inspector.get_indexes("book")
        index_columns = [idx["column_names"] for idx in indexes]

        assert any("source" in cols for cols in index_columns)

    def test_book_composite_unique_root_path(self, schema_db):
        """Verify (root_folder_id, file_path) is unique."""
        from backend.models.book import RootFolder

        root = RootFolder(name="Test Root", path="/test")
        schema_db.add(root)
        schema_db.flush()

        book1 = Book(
            title="Book 1",
            hardcover_id="hc-1",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=root.id,
            file_path="books/book1.epub",
        )
        schema_db.add(book1)
        schema_db.commit()

        book2 = Book(
            title="Book 2",
            hardcover_id="hc-2",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=root.id,
            file_path="books/book1.epub",
        )
        schema_db.add(book2)

        with pytest.raises(IntegrityError):
            schema_db.commit()

    def test_book_composite_unique_allows_null_file_path(self, schema_db):
        """Verify multiple books can have NULL file_path."""
        book1 = Book(title="Book 1", hardcover_id="hc-1", status=BookStatus.WANTED.value, file_path=None)
        book2 = Book(title="Book 2", hardcover_id="hc-2", status=BookStatus.WANTED.value, file_path=None)
        schema_db.add_all([book1, book2])
        schema_db.commit()

        assert book1.id is not None
        assert book2.id is not None

    def test_book_composite_unique_same_path_different_root(self, schema_db):
        """Verify same file_path can exist in different root folders."""
        from backend.models.book import RootFolder

        root1 = RootFolder(name="Root 1", path="/root1")
        root2 = RootFolder(name="Root 2", path="/root2")
        schema_db.add_all([root1, root2])
        schema_db.flush()

        book1 = Book(
            title="Book 1",
            hardcover_id="hc-1",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=root1.id,
            file_path="books/book.epub",
        )
        book2 = Book(
            title="Book 2",
            hardcover_id="hc-2",
            status=BookStatus.IN_LIBRARY.value,
            root_folder_id=root2.id,
            file_path="books/book.epub",
        )
        schema_db.add_all([book1, book2])
        schema_db.commit()

        assert book1.id is not None
        assert book2.id is not None


class TestScanStatusEnum:
    """Test ScanStatus enum values."""

    def test_scan_status_values(self):
        """Verify ScanStatus has expected values."""
        assert ScanStatus.RUNNING.value == "running"
        assert ScanStatus.COMPLETED.value == "completed"
        assert ScanStatus.FAILED.value == "failed"
        assert ScanStatus.CANCELLED.value == "cancelled"


class TestMatchProposalStatusEnum:
    """Test MatchProposalStatus enum values."""

    def test_match_proposal_status_values(self):
        """Verify MatchProposalStatus has expected values."""
        assert MatchProposalStatus.PENDING.value == "pending"
        assert MatchProposalStatus.APPROVED.value == "approved"
        assert MatchProposalStatus.REJECTED.value == "rejected"
        assert MatchProposalStatus.AUTO_LINKED.value == "auto_linked"
        assert MatchProposalStatus.SUPERSEDED.value == "superseded"
