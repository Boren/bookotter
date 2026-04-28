# pyright: reportGeneralTypeIssues=false, reportArgumentType=false

import pytest
from sqlalchemy.exc import IntegrityError

from backend.services.blocklist_service import BlocklistService


class TestBlocklistService:
    def test_add_entry(self, db_session):
        service = BlocklistService(db_session)

        entry = service.add("IndexerA", "guid-1", "Test Title", "Bad release")

        assert entry.id is not None
        assert entry.indexer == "IndexerA"
        assert entry.release_guid == "guid-1"
        assert entry.reason == "Bad release"

    def test_duplicate_raises(self, db_session):
        service = BlocklistService(db_session)
        service.add("IndexerA", "guid-1", "Test Title")

        with pytest.raises(IntegrityError):
            service.add("IndexerA", "guid-1", "Test Title")

    def test_remove_entry(self, db_session):
        service = BlocklistService(db_session)
        entry = service.add("IndexerA", "guid-1", "Test Title")

        assert service.remove(entry.id) is True
        assert service.list_all() == []

    def test_is_blocklisted(self, db_session):
        service = BlocklistService(db_session)
        service.add("IndexerA", "guid-1", "Test Title")

        assert service.is_blocklisted("IndexerA", "guid-1") is True

    def test_get_set(self, db_session):
        service = BlocklistService(db_session)
        service.add("IndexerA", "guid-1", "Title 1")
        service.add("IndexerB", "guid-2", "Title 2")

        assert service.get_set() == {("IndexerA", "guid-1"), ("IndexerB", "guid-2")}

    def test_different_indexer_not_blocklisted(self, db_session):
        service = BlocklistService(db_session)
        service.add("IndexerA", "guid-1", "Test Title")

        assert service.is_blocklisted("IndexerB", "guid-1") is False
