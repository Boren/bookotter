"""
Database configuration and SQLAlchemy setup for BookOtter.
Uses SQLite for storing sync history and book results.
Schedules are now stored in config.yaml (not in the database).
"""

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
Base = declarative_base()


def get_db():
    """Dependency for FastAPI routes to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all database tables."""
    from backend.models import blocklist, book  # noqa: F401 - Import models to register them

    Base.metadata.create_all(bind=engine)
    backfill_missing_status()


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

            book.status = BookStatus.MISSING.value  # pyright: ignore[reportAttributeAccessIssue]
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
