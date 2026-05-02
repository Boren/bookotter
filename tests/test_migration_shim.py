# pyright: reportGeneralTypeIssues=false

import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.database import Base
from backend.models import blocklist, rss  # noqa: F401 - register metadata tables
from backend.models.book import BookStatus  # noqa: F401 - register book metadata tables


def _configure_test_database(monkeypatch, db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    return engine, session_local


def _sqlite_columns(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _create_missing_low_confidence_fixture(db_path: Path) -> list[dict]:
    seeded_rows = [
        {
            "id": 1,
            "title": "Fixture Book One",
            "author_id": 1,
            "hardcover_id": "100",
            "isbn": "978-0-123456-00-1",
            "description": "Fixture description one",
            "publisher": "Fixture Publisher",
            "language": "en",
            "tags": json.dumps(["alpha", "beta"]),
            "rating": 4.5,
            "read_date": "2025-01-01 10:00:00",
            "cover_url": "https://example.com/one.jpg",
            "series_name": "Series A",
            "series_position": 1.0,
            "status": BookStatus.IN_LIBRARY.value,
            "root_folder_id": None,
            "file_path": "library/one.epub",
            "file_size": 1234,
            "search_attempts": 1,
            "last_searched_at": "2025-01-01 11:00:00",
            "created_at": "2025-01-01 09:00:00",
            "updated_at": "2025-01-01 12:00:00",
            "failure_reason": None,
            "retry_count": 0,
            "kindle_delivery_status": None,
            "kindle_delivery_attempts": 0,
            "kindle_first_pending_at": None,
        },
        {
            "id": 2,
            "title": "Fixture Book Two",
            "author_id": 1,
            "hardcover_id": "200",
            "isbn": "978-0-123456-00-2",
            "description": "Fixture description two",
            "publisher": "Fixture Publisher",
            "language": "no",
            "tags": json.dumps(["gamma"]),
            "rating": 3.75,
            "read_date": None,
            "cover_url": "https://example.com/two.jpg",
            "series_name": None,
            "series_position": None,
            "status": BookStatus.IN_LIBRARY.value,
            "root_folder_id": None,
            "file_path": "library/two.epub",
            "file_size": 2345,
            "search_attempts": 2,
            "last_searched_at": "2025-01-02 11:00:00",
            "created_at": "2025-01-02 09:00:00",
            "updated_at": "2025-01-02 12:00:00",
            "failure_reason": "temporary_failure",
            "retry_count": 1,
            "kindle_delivery_status": "PENDING",
            "kindle_delivery_attempts": 1,
            "kindle_first_pending_at": "2025-01-02 12:30:00",
        },
        {
            "id": 3,
            "title": "Fixture Book Three",
            "author_id": 1,
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
            "file_path": "library/three.epub",
            "file_size": None,
            "search_attempts": 0,
            "last_searched_at": None,
            "created_at": "2025-01-03 09:00:00",
            "updated_at": "2025-01-03 12:00:00",
            "failure_reason": None,
            "retry_count": 2,
            "kindle_delivery_status": "DELIVERED",
            "kindle_delivery_attempts": 2,
            "kindle_first_pending_at": "2025-01-03 12:30:00",
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
                kindle_delivery_status TEXT,
                kindle_delivery_attempts INTEGER NOT NULL,
                kindle_first_pending_at DATETIME,
                PRIMARY KEY (id)
            );
            """
        )

        conn.execute(
            "INSERT INTO author (id, name, hardcover_id, created_at) VALUES (?, ?, ?, ?)",
            (1, "Fixture Author", None, "2025-01-01 08:00:00"),
        )

        insert_sql = """
            INSERT INTO book (
                id, title, author_id, hardcover_id, isbn, description, publisher, language, tags, rating,
                read_date, cover_url, series_name, series_position, status, root_folder_id, file_path,
                file_size, search_attempts, last_searched_at, created_at, updated_at, failure_reason,
                retry_count, kindle_delivery_status, kindle_delivery_attempts, kindle_first_pending_at
            ) VALUES (
                :id, :title, :author_id, :hardcover_id, :isbn, :description, :publisher, :language, :tags,
                :rating, :read_date, :cover_url, :series_name, :series_position, :status, :root_folder_id,
                :file_path, :file_size, :search_attempts, :last_searched_at, :created_at, :updated_at,
                :failure_reason, :retry_count, :kindle_delivery_status, :kindle_delivery_attempts,
                :kindle_first_pending_at
            )
        """
        conn.executemany(insert_sql, seeded_rows)
        conn.commit()

    return seeded_rows


def test_init_db_creates_all_metadata_columns_for_fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    engine, _session_local = _configure_test_database(monkeypatch, db_path)

    database.init_db()

    for table_name, table in Base.metadata.tables.items():
        assert {column.name for column in table.columns} <= _sqlite_columns(engine, table_name)

    engine.dispose()


def test_init_db_restores_missing_column_without_losing_existing_book_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "missing-low-confidence.db"
    expected_rows = _create_missing_low_confidence_fixture(db_path)
    engine, _session_local = _configure_test_database(monkeypatch, db_path)

    database.init_db()

    assert "low_confidence" in _sqlite_columns(engine, "book")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        actual_rows = [dict(row) for row in conn.execute("SELECT * FROM book ORDER BY id").fetchall()]

    assert [row["hardcover_id"] for row in actual_rows] == ["100", "200", "300"]

    for expected_row, actual_row in zip(expected_rows, actual_rows, strict=True):
        for column_name, expected_value in expected_row.items():
            assert actual_row[column_name] == expected_value
        assert actual_row["low_confidence"] == 0

    engine.dispose()


def test_init_db_is_idempotent_when_schema_is_already_current(tmp_path, monkeypatch):
    db_path = tmp_path / "idempotent.db"
    engine, _session_local = _configure_test_database(monkeypatch, db_path)

    database.init_db()

    alter_statements: list[str] = []

    def _capture_alter(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("ALTER TABLE"):
            alter_statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture_alter)
    try:
        database.init_db()
    finally:
        event.remove(engine, "before_cursor_execute", _capture_alter)
        engine.dispose()

    assert alter_statements == []
