"""
RSS feed tracking models for Prowlarr indexer synchronization.
Tracks seen items and indexer state for RSS-based book discovery.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class RssSeenItem(Base):
    """Tracks RSS items that have been seen to avoid duplicate processing."""

    __tablename__ = "rss_seen_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    indexer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    guid: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("indexer_id", "guid", name="uq_rss_seen_item"),)


class RssIndexerState(Base):
    """Tracks state and metadata for each Prowlarr indexer's RSS feed."""

    __tablename__ = "rss_indexer_state"

    indexer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indexer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    items_seen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_grabbed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_not_before_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    caps_cached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    caps_supports_book_search: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
