"""
Database configuration and SQLAlchemy setup for BookOtter.
Uses SQLite for storing sync history and book results.
Schedules are now stored in config.yaml (not in the database).
"""

import json
import logging
import os
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

# Default database path - can be overridden via environment variable
DATA_DIR = os.environ.get("BOOKOTTER_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DATABASE_URL = os.environ.get("BOOKOTTER_DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'bookotter.db')}")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# SQLAlchemy setup
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite with FastAPI
    echo=False,  # Set to True for SQL query logging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency for FastAPI routes to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _refuse_legacy_kindle_schema(db_engine) -> None:
    """Fail fast before create_all/column-add can plant empty ereader_* columns
    next to legacy kindle_* data, which would reset delivery state and trigger
    a mass re-send/delete in the mirror sync."""
    from backend.services.ereader_migration import COLUMN_RENAMES, UnmigratedKindleStateError

    inspector = inspect(db_engine)
    if "book" not in inspector.get_table_names():
        return
    legacy = {column["name"] for column in inspector.get_columns("book")} & set(COLUMN_RENAMES)
    if legacy:
        msg = (
            f"Database has legacy Kindle-era columns {sorted(legacy)}. "
            "Run `python -m backend.cli migrate-to-ereader` before starting this version."
        )
        raise UnmigratedKindleStateError(msg)


def init_db():
    """Create all database tables."""
    from backend.models import blocklist, book  # noqa: F401 - Import models to register them

    _refuse_legacy_kindle_schema(engine)
    Base.metadata.create_all(bind=engine)
    _apply_pending_column_migrations(engine)
    backfill_missing_status()


def _apply_pending_column_migrations(db_engine) -> None:
    """Add any metadata-defined columns missing from existing SQLite tables."""
    inspector = inspect(db_engine)

    with db_engine.connect() as conn:
        transaction = conn.begin()
        try:
            for table_name, table in Base.metadata.tables.items():
                existing_columns = {column["name"] for column in inspector.get_columns(table_name)}

                for column in table.columns:
                    if column.name in existing_columns:
                        continue

                    ddl = _build_add_column_ddl(table_name, column)
                    logger.info("Applying pending column migration: %s", ddl)
                    conn.execute(text(ddl))
                    existing_columns.add(column.name)

            transaction.commit()
        except Exception:
            transaction.rollback()
            raise


def _build_add_column_ddl(table_name, column) -> str:
    column_definition = [
        _quote_sqlite_identifier(column.name),
        _sqlite_column_type(column),
    ]

    if not column.nullable:
        column_definition.append(f"DEFAULT {_sqlite_default_sql(column)}")
        column_definition.append("NOT NULL")

    return f"ALTER TABLE {_quote_sqlite_identifier(table_name)} ADD COLUMN {' '.join(column_definition)}"


def _sqlite_column_type(column) -> str:
    if isinstance(column.type, Integer):
        return "INTEGER"
    if isinstance(column.type, (String, Text, JSON)):
        return "TEXT"
    if isinstance(column.type, DateTime):
        return "DATETIME"
    if isinstance(column.type, Boolean):
        return "BOOLEAN"
    if isinstance(column.type, Float):
        return "REAL"

    msg = f"Unsupported SQLite migration type for {column.table.name}.{column.name}: {column.type!r}"
    raise ValueError(msg)


def _sqlite_default_sql(column) -> str:
    default = column.default.arg if column.default is not None else None

    if callable(default):
        default = None

    if isinstance(default, Enum):
        default = default.value

    if default is None:
        return _sqlite_fallback_default_sql(column)

    if isinstance(default, bool):
        return "1" if default else "0"
    if isinstance(default, int | float):
        return str(default)
    if isinstance(default, datetime):
        return _quote_sqlite_string(default.isoformat(sep=" "))
    if isinstance(default, (dict, list)):
        return _quote_sqlite_string(json.dumps(default))
    if isinstance(default, str):
        return _quote_sqlite_string(default)

    return _quote_sqlite_string(str(default))


def _sqlite_fallback_default_sql(column) -> str:
    sqlite_type = _sqlite_column_type(column)

    if sqlite_type in {"INTEGER", "REAL", "BOOLEAN"}:
        return "0"
    if sqlite_type == "DATETIME":
        return _quote_sqlite_string("1970-01-01 00:00:00")
    return _quote_sqlite_string("")


def _quote_sqlite_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _quote_sqlite_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def backfill_missing_status() -> int:
    """Convert idle WANTED books with no files/downloads to MISSING."""
    from backend.models.book import Book, BookStatus, DownloadStatus

    db = SessionLocal()
    converted = 0
    active_download_statuses = {DownloadStatus.QUEUED.value, DownloadStatus.DOWNLOADING.value}

    try:
        wanted_books = db.query(Book).filter(Book.status == BookStatus.WANTED.value, Book.file_path.is_(None)).all()

        for book in wanted_books:
            has_active_download = any(download.status in active_download_statuses for download in book.downloads)
            if has_active_download:
                continue

            book.status = BookStatus.MISSING.value
            converted += 1

        db.commit()
        if converted:
            logger.info("Backfilled %s WANTED book(s) to MISSING", converted)
        return converted
    except Exception as exc:
        db.rollback()
        logger.error("Missing-status backfill failed: %s", exc)
        return 0
    finally:
        db.close()
