"""
Database models for library scanner functionality.
Tracks scan runs, match proposals, and dismissed paths.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ScanStatus(StrEnum):
    """Status of a library scan run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Scan(Base):
    """Represents a library scan run."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    root_folder_id: Mapped[int] = mapped_column(Integer, ForeignKey("root_folder.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ScanStatus.RUNNING.value, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    files_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_proposed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_unmatched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MatchProposalStatus(StrEnum):
    """Status of a match proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_LINKED = "auto_linked"
    SUPERSEDED = "superseded"


class MatchProposal(Base):
    """Represents a proposed match between a scanned file and a book."""

    __tablename__ = "match_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_id: Mapped[int] = mapped_column(Integer, ForeignKey("scans.id"), nullable=False, index=True)
    root_folder_id: Mapped[int] = mapped_column(Integer, ForeignKey("root_folder.id"), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)  # NFC-normalized
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("book.id"), nullable=True, index=True)
    match_method: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # String to avoid circular import from scanner.types
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MatchProposalStatus.PENDING.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_proposals_status_root", "status", "root_folder_id"),)


class DismissedScanPath(Base):
    """Represents a file path that was dismissed during scanning."""

    __tablename__ = "dismissed_scan_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    root_folder_id: Mapped[int] = mapped_column(Integer, ForeignKey("root_folder.id"), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("root_folder_id", "relative_path", name="uq_dismissed_path"),)
