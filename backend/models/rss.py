"""
RSS feed tracking models for Prowlarr indexer synchronization.
Tracks seen items and indexer state for RSS-based book discovery.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from backend.database import Base


class RssSeenItem(Base):
    """Tracks RSS items that have been seen to avoid duplicate processing."""

    __tablename__ = "rss_seen_item"

    id = Column(Integer, primary_key=True, index=True)
    indexer_id = Column(Integer, nullable=False, index=True)
    guid = Column(String(500), nullable=False, index=True)
    seen_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("indexer_id", "guid", name="uq_rss_seen_item"),)


class RssIndexerState(Base):
    """Tracks state and metadata for each Prowlarr indexer's RSS feed."""

    __tablename__ = "rss_indexer_state"

    indexer_id = Column(Integer, primary_key=True)
    indexer_name = Column(String(255), nullable=True)
    last_poll_at = Column(DateTime, nullable=True)
    last_status = Column(String(50), nullable=True)
    last_error = Column(String(500), nullable=True)
    items_seen_count = Column(Integer, default=0, nullable=False)
    items_grabbed_count = Column(Integer, default=0, nullable=False)
    retry_not_before_at = Column(DateTime, nullable=True)
    caps_cached_at = Column(DateTime, nullable=True)
    caps_supports_book_search = Column(Boolean, nullable=True)
