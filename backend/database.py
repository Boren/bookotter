"""
Database configuration and SQLAlchemy setup for BookOtter.
Uses SQLite for storing sync history and book results.
Schedules are now stored in config.yaml (not in the database).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
    from backend.models import sync_run  # noqa: F401 - Import models to register them

    Base.metadata.create_all(bind=engine)
