from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String

from backend.database import Base


class BlocklistEntry(Base):
    __tablename__ = "blocklist_entry"

    id = Column(Integer, primary_key=True)
    indexer = Column(String(100), nullable=False)
    release_guid = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
