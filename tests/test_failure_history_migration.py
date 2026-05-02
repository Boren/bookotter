# pyright: reportGeneralTypeIssues=false

import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.database import Base
from backend.models import blocklist, rss  # noqa: F401 - register metadata tables
from backend.models.book import Book, BookStatus  # noqa: F401 - register book metadata tables


def _configure_test_database(monkeypatch, db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    return engine, session_local


def _sqlite_columns(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def test_failure_history_column_round_trip(tmp_path, monkeypatch):
    """Test that failure_history JSON column can be written and read back correctly."""
    db_path = tmp_path / "round_trip.db"
    engine, session_local = _configure_test_database(monkeypatch, db_path)

    # Initialize database with current schema
    Base.metadata.create_all(bind=engine)

    session = session_local()
    try:
        # Create a book with failure_history
        failure_history = [
            {"reason": "download_stalled", "timestamp": "2026-01-01T00:00:00Z", "attempt": 1}
        ]
        book = Book(
            title="Test Book",
            author_id=None,
            hardcover_id="test-123",
            status=BookStatus.WANTED.value,
            failure_history=failure_history,
        )
        session.add(book)
        session.commit()
        book_id = book.id

        # Reload from database
        session.expunge_all()
        reloaded_book = session.query(Book).filter(Book.id == book_id).first()

        # Assert deep equality
        assert reloaded_book is not None
        assert reloaded_book.failure_history == failure_history
        assert reloaded_book.failure_history[0]["reason"] == "download_stalled"
        assert reloaded_book.failure_history[0]["timestamp"] == "2026-01-01T00:00:00Z"
        assert reloaded_book.failure_history[0]["attempt"] == 1
    finally:
        session.close()
        engine.dispose()


def test_failure_history_migration_from_pre_t6_db(tmp_path, monkeypatch):
    """Test that init_db adds failure_history column to pre-T6 databases without losing data."""
    db_path = tmp_path / "pre_t6.db"

    # Create a pre-T6 database (without failure_history column)
    seeded_rows = [
        {
            "id": 1,
            "title": "Book One",
            "author_id": None,
            "hardcover_id": "100",
            "isbn": None,
            "description": None,
            "publisher": None,
            "language": None,
            "tags": None,
            "rating": None,
            "read_date": None,
            "cover_url": None,
            "series_name": None,
            "series_position": None,
            "status": BookStatus.WANTED.value,
            "root_folder_id": None,
            "file_path": None,
            "file_size": None,
            "search_attempts": 0,
            "last_searched_at": None,
            "created_at": "2025-01-01 09:00:00",
            "updated_at": "2025-01-01 12:00:00",
            "failure_reason": None,
            "retry_count": 0,
            "low_confidence": 0,
            "kindle_delivery_status": None,
            "kindle_delivery_attempts": 0,
            "kindle_first_pending_at": None,
        },
        {
            "id": 2,
            "title": "Book Two",
            "author_id": None,
            "hardcover_id": "200",
            "isbn": None,
            "description": None,
            "publisher": None,
            "language": None,
            "tags": None,
            "rating": None,
            "read_date": None,
            "cover_url": None,
            "series_name": None,
            "series_position": None,
            "status": BookStatus.IN_LIBRARY.value,
            "root_folder_id": None,
            "file_path": None,
            "file_size": None,
            "search_attempts": 0,
            "last_searched_at": None,
            "created_at": "2025-01-02 09:00:00",
            "updated_at": "2025-01-02 12:00:00",
            "failure_reason": None,
            "retry_count": 0,
            "low_confidence": 0,
            "kindle_delivery_status": None,
            "kindle_delivery_attempts": 0,
            "kindle_first_pending_at": None,
        },
        {
            "id": 3,
            "title": "Book Three",
            "author_id": None,
            "hardcover_id": "300",
            "isbn": None,
            "description": None,
            "publisher": None,
            "language": None,
            "tags": None,
            "rating": None,
            "read_date": None,
            "cover_url": None,
            "series_name": None,
            "series_position": None,
            "status": BookStatus.GRABBED.value,
            "root_folder_id": None,
            "file_path": None,
            "file_size": None,
            "search_attempts": 0,
            "last_searched_at": None,
            "created_at": "2025-01-03 09:00:00",
            "updated_at": "2025-01-03 12:00:00",
            "failure_reason": None,
            "retry_count": 0,
            "low_confidence": 0,
            "kindle_delivery_status": None,
            "kindle_delivery_attempts": 0,
            "kindle_first_pending_at": None,
        },
    ]

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE author (
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                hardcover_id TEXT,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (name)
            );

            CREATE TABLE book (
                id INTEGER NOT NULL,
                title TEXT NOT NULL,
                author_id INTEGER,
                hardcover_id TEXT,
                isbn TEXT,
                description TEXT,
                publisher TEXT,
                language TEXT,
                tags TEXT,
                rating REAL,
                read_date DATETIME,
                cover_url TEXT,
                series_name TEXT,
                series_position REAL,
                status TEXT NOT NULL,
                root_folder_id INTEGER,
                file_path TEXT,
                file_size INTEGER,
                search_attempts INTEGER,
                last_searched_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                failure_reason TEXT,
                retry_count INTEGER NOT NULL,
                low_confidence INTEGER NOT NULL,
                kindle_delivery_status TEXT,
                kindle_delivery_attempts INTEGER NOT NULL,
                kindle_first_pending_at DATETIME,
                PRIMARY KEY (id)
            );
            """
        )

        insert_sql = """
            INSERT INTO book (
                id, title, author_id, hardcover_id, isbn, description, publisher, language, tags, rating,
                read_date, cover_url, series_name, series_position, status, root_folder_id, file_path,
                file_size, search_attempts, last_searched_at, created_at, updated_at, failure_reason,
                retry_count, low_confidence, kindle_delivery_status, kindle_delivery_attempts, kindle_first_pending_at
            ) VALUES (
                :id, :title, :author_id, :hardcover_id, :isbn, :description, :publisher, :language, :tags,
                :rating, :read_date, :cover_url, :series_name, :series_position, :status, :root_folder_id,
                :file_path, :file_size, :search_attempts, :last_searched_at, :created_at, :updated_at,
                :failure_reason, :retry_count, :low_confidence, :kindle_delivery_status, :kindle_delivery_attempts,
                :kindle_first_pending_at
            )
        """
        conn.executemany(insert_sql, seeded_rows)
        conn.commit()

    # Verify pre-T6 schema (no failure_history column)
    engine, _session_local = _configure_test_database(monkeypatch, db_path)
    assert "failure_history" not in _sqlite_columns(engine, "book")

    # Run init_db to migrate schema
    database.init_db()

    # Verify failure_history column now exists
    assert "failure_history" in _sqlite_columns(engine, "book")

    # Verify all 3 rows still exist with correct hardcover_ids
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        actual_rows = [dict(row) for row in conn.execute("SELECT * FROM book ORDER BY id").fetchall()]

    assert len(actual_rows) == 3
    assert [row["hardcover_id"] for row in actual_rows] == ["100", "200", "300"]

    # Verify failure_history is NULL for all rows
    for row in actual_rows:
        assert row["failure_history"] is None

    engine.dispose()
