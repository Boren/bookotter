from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class BlocklistEntry(Base):
    __tablename__ = "blocklist_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indexer: Mapped[str] = mapped_column(String(100), nullable=False)
    release_guid: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    __table_args__ = (Index("ix_blocklist_indexer_guid", "indexer", "release_guid", unique=True),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "indexer": self.indexer,
            "release_guid": self.release_guid,
            "title": self.title,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }
