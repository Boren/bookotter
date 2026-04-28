"""Tests for blocklist API routes — calls route functions directly (no TestClient)."""

import asyncio

import pytest

from backend.api.routes import blocklist as blocklist_routes
from backend.services.blocklist_service import BlocklistService


def _add(db, indexer: str, guid: str, title: str, reason: str | None = None):
    """Helper: add a blocklist entry via service."""
    return BlocklistService(db).add(indexer, guid, title, reason)


class TestListBlocklist:
    def test_list_empty(self, db_session):
        result = asyncio.run(blocklist_routes.list_blocklist(db=db_session))
        assert result == {"entries": [], "total": 0}

    def test_list_returns_entries(self, db_session):
        _add(db_session, "idx", "g1", "Title One")
        _add(db_session, "idx", "g2", "Title Two")
        result = asyncio.run(blocklist_routes.list_blocklist(db=db_session))
        assert result["total"] == 2
        guids = {e["release_guid"] for e in result["entries"]}
        assert guids == {"g1", "g2"}


class TestAddBlocklistEntry:
    def test_add_entry_returns_201_data(self, db_session):
        body = blocklist_routes.BlocklistCreateRequest(
            indexer="TestIndexer",
            release_guid="guid-123",
            title="Test Release",
            reason="Bad quality",
        )
        result = asyncio.run(blocklist_routes.create_blocklist_entry(body=body, db=db_session))
        assert result["indexer"] == "TestIndexer"
        assert result["release_guid"] == "guid-123"
        assert result["title"] == "Test Release"
        assert result["reason"] == "Bad quality"
        assert "id" in result

    def test_add_duplicate_raises_409(self, db_session):
        from fastapi import HTTPException

        body = blocklist_routes.BlocklistCreateRequest(
            indexer="TestIndexer",
            release_guid="guid-123",
            title="Test Release",
        )
        asyncio.run(blocklist_routes.create_blocklist_entry(body=body, db=db_session))
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(blocklist_routes.create_blocklist_entry(body=body, db=db_session))
        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.detail


class TestDeleteBlocklistEntry:
    def test_delete_entry(self, db_session):
        entry = _add(db_session, "TestIndexer", "guid-123", "Test Release")
        asyncio.run(blocklist_routes.delete_blocklist_entry(entry_id=entry.id, db=db_session))
        result = asyncio.run(blocklist_routes.list_blocklist(db=db_session))
        assert result["total"] == 0

    def test_delete_nonexistent_raises_404(self, db_session):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(blocklist_routes.delete_blocklist_entry(entry_id=999, db=db_session))
        assert exc_info.value.status_code == 404


class TestFromReleaseEndpoint:
    def test_from_release_adds_entry(self, db_session):
        body = blocklist_routes.BlocklistFromReleaseRequest(
            indexer="TestIndexer",
            release_guid="guid-456",
            title="Another Release",
            reason="Wrong language",
        )
        result = asyncio.run(blocklist_routes.blocklist_from_release(body=body, db=db_session))
        assert result["indexer"] == "TestIndexer"
        assert result["release_guid"] == "guid-456"
        assert result["title"] == "Another Release"
        assert result["reason"] == "Wrong language"
        assert "id" in result

    def test_from_release_duplicate_raises_409(self, db_session):
        from fastapi import HTTPException

        body = blocklist_routes.BlocklistFromReleaseRequest(
            indexer="TestIndexer",
            release_guid="guid-456",
            title="Another Release",
        )
        asyncio.run(blocklist_routes.blocklist_from_release(body=body, db=db_session))
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(blocklist_routes.blocklist_from_release(body=body, db=db_session))
        assert exc_info.value.status_code == 409
