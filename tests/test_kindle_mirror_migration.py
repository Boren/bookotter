"""Migration + defaults tests for the Kindle shelf-mirror columns and config."""

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.config import get_default_config, get_kindle_sync_shelves
from backend.database import Base
from backend.models import blocklist, rss  # noqa: F401 - register metadata tables
from backend.models.book import Book, BookStatus  # noqa: F401 - register book metadata tables


def _configure_test_database(monkeypatch, db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    return engine, session_local


def test_init_db_adds_mirror_columns_to_existing_db(tmp_path, monkeypatch):
    """A pre-mirror database gains hardcover_status and kindle_pinned without data loss."""
    db_path = tmp_path / "pre_mirror.db"
    engine, session_local = _configure_test_database(monkeypatch, db_path)

    # Build the current schema, then strip the two new columns to simulate an
    # older database (SQLite supports DROP COLUMN since 3.35).
    Base.metadata.create_all(bind=engine)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS ix_book_hardcover_status")
        conn.execute("ALTER TABLE book DROP COLUMN hardcover_status")
        conn.execute("ALTER TABLE book DROP COLUMN kindle_pinned")
        conn.execute(
            "INSERT INTO book (title, hardcover_id, status, created_at, updated_at,"
            " retry_count, low_confidence, kindle_delivery_attempts)"
            " VALUES ('Old Book', 'hc-old', 'in_library', '2025-01-01', '2025-01-01', 0, 0, 0)"
        )
        conn.commit()

    database.init_db()

    columns = {c["name"] for c in inspect(engine).get_columns("book")}
    assert "hardcover_status" in columns
    assert "kindle_pinned" in columns

    session = session_local()
    try:
        book = session.query(Book).filter(Book.hardcover_id == "hc-old").one()
        assert book.hardcover_status is None
        assert book.kindle_pinned is False
    finally:
        session.close()
        engine.dispose()


def test_default_config_contains_sync_shelves():
    cfg = get_default_config()
    assert cfg["transfer"]["sync_shelves"] == {
        "want_to_read": True,
        "currently_reading": True,
        "read": False,
    }
    assert cfg["transfer"]["cleanup_enabled"] is True
    assert "skip_existing" not in cfg["transfer"]
    for actions in cfg["pipeline"]["status_actions"].values():
        assert "kindle_sync" not in actions


def test_get_kindle_sync_shelves_reads_enabled_names():
    cfg = {"transfer": {"sync_shelves": {"want_to_read": True, "currently_reading": False, "read": True}}}
    assert get_kindle_sync_shelves(cfg) == {"want_to_read", "read"}


def test_get_kindle_sync_shelves_empty_when_missing():
    assert get_kindle_sync_shelves({"transfer": {}}) == set()
