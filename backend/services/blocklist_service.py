from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.blocklist import BlocklistEntry


class BlocklistService:
    def __init__(self, db: Session):
        self.db = db

    def add(self, indexer: str, release_guid: str, title: str, reason: str | None = None) -> BlocklistEntry:
        entry = BlocklistEntry(indexer=indexer, release_guid=release_guid, title=title, reason=reason)
        self.db.add(entry)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise

        self.db.refresh(entry)
        return entry

    def remove(self, entry_id: int) -> bool:
        entry = self.db.query(BlocklistEntry).filter(BlocklistEntry.id == entry_id).first()
        if not entry:
            return False

        self.db.delete(entry)
        self.db.commit()
        return True

    def is_blocklisted(self, indexer: str, release_guid: str) -> bool:
        return (
            self.db.query(BlocklistEntry)
            .filter(BlocklistEntry.indexer == indexer, BlocklistEntry.release_guid == release_guid)
            .first()
            is not None
        )

    def list_all(self) -> list[BlocklistEntry]:
        return self.db.query(BlocklistEntry).order_by(BlocklistEntry.created_at.desc(), BlocklistEntry.id.desc()).all()

    def get_set(self) -> set[tuple[str, str]]:
        entries = self.db.query(BlocklistEntry.indexer, BlocklistEntry.release_guid).all()
        return {(indexer, release_guid) for indexer, release_guid in entries}
