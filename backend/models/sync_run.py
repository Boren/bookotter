"""
Database models for sync runs and book results.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class SyncRun(Base):
    """Represents a single sync execution."""

    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed, cancelled
    trigger_type = Column(String(20), nullable=False)  # manual, scheduled
    kindle_device = Column(String(100), nullable=True)  # Which Kindle was targeted

    # Stats
    total_books = Column(Integer, default=0)
    matched = Column(Integer, default=0)
    transferred = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    not_found = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    added_to_readarr = Column(Integer, default=0)
    add_failures = Column(Integer, default=0)
    cleaned_up = Column(Integer, default=0)  # Number of books removed from Kindle

    # Configuration at time of run
    status_ids = Column(JSON, default=lambda: [1])  # Which Hardcover statuses were synced
    dry_run = Column(Boolean, default=False)

    # Error info
    error_message = Column(Text, nullable=True)

    # Relationship to book results
    book_results = relationship("BookResult", back_populates="sync_run", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "kindle_device": self.kindle_device,
            "total_books": self.total_books,
            "matched": self.matched,
            "transferred": self.transferred,
            "failed": self.failed,
            "not_found": self.not_found,
            "skipped": self.skipped,
            "added_to_readarr": self.added_to_readarr,
            "add_failures": self.add_failures,
            "cleaned_up": self.cleaned_up,
            "status_ids": self.status_ids,
            "dry_run": self.dry_run,
            "error_message": self.error_message,
        }


class BookResult(Base):
    """Represents the result of processing a single book in a sync run."""

    __tablename__ = "book_results"

    id = Column(Integer, primary_key=True, index=True)
    sync_run_id = Column(Integer, ForeignKey("sync_runs.id"), nullable=False, index=True)

    # Book identification
    hardcover_id = Column(String(100), nullable=True)
    title = Column(String(500), nullable=False)
    author = Column(String(500), nullable=True)
    isbns = Column(JSON, nullable=True)  # List of ISBNs
    cover_url = Column(String(500), nullable=True)  # Cover image URL from Hardcover

    # Result
    status = Column(
        String(30), nullable=False
    )  # matched, transferred, skipped, not_found, failed, added_to_readarr, removed
    reading_status = Column(String(20), nullable=True)  # want_to_read, currently_reading, read
    match_method = Column(String(20), nullable=True)  # isbn, fuzzy
    match_score = Column(Integer, nullable=True)  # Fuzzy match score if applicable
    readarr_book_id = Column(Integer, nullable=True)
    file_path = Column(String(1000), nullable=True)
    file_size = Column(Integer, nullable=True)  # Bytes
    error_message = Column(Text, nullable=True)

    processed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    sync_run = relationship("SyncRun", back_populates="book_results")

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "sync_run_id": self.sync_run_id,
            "hardcover_id": self.hardcover_id,
            "title": self.title,
            "author": self.author,
            "isbns": self.isbns,
            "cover_url": self.cover_url,
            "status": self.status,
            "reading_status": self.reading_status,
            "match_method": self.match_method,
            "match_score": self.match_score,
            "readarr_book_id": self.readarr_book_id,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "error_message": self.error_message,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }
