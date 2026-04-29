"""Dead-letter queue style queries for failed books."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.errors import FailureReason
from backend.models.book import Book, BookStatus


def get_permanent_failed(db: Session, limit: int = 100, offset: int = 0) -> list[Book]:
    """Return books in PERMANENT_FAILED state."""
    return (
        db.query(Book)
        .filter(Book.status == BookStatus.PERMANENT_FAILED.value)
        .order_by(Book.updated_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_recent_failures(db: Session, hours: int = 24, limit: int = 100) -> list[Book]:
    """Return books that failed within the last N hours (FAILED state only, not PERMANENT_FAILED)."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    return (
        db.query(Book)
        .filter(
            Book.status == BookStatus.FAILED.value,
            Book.updated_at >= cutoff,
        )
        .order_by(Book.updated_at.desc())
        .limit(limit)
        .all()
    )


def get_failures_by_reason(db: Session, reason: FailureReason) -> list[Book]:
    """Return books with a specific failure reason."""
    return (
        db.query(Book)
        .filter(Book.failure_reason == reason.value)
        .order_by(Book.updated_at.desc())
        .all()
    )
