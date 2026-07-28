"""Tests for auto-search wiring when a book is added manually via the API."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import BackgroundTasks

from backend.api.routes.library import BookCreateRequest, create_book
from backend.models.book import BookStatus


def _make_request(pipeline=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pipeline=pipeline)))


def _make_config(search_on_add: bool = True) -> dict:
    return {"pipeline": {"search_on_add": search_on_add}}


def _create(db, monkeypatch, *, search_on_add=True, pipeline=None, status=BookStatus.WANTED.value):
    monkeypatch.setattr("backend.api.routes.library.load_config", lambda: _make_config(search_on_add))
    request = _make_request(pipeline=pipeline)
    background_tasks = BackgroundTasks()
    body = BookCreateRequest(title="Added Book", author_name="Added Author", status=status)
    payload = asyncio.run(create_book(body, request, background_tasks, db))
    return payload, background_tasks


class TestCreateBookSearchOnAdd:
    def test_schedules_search_when_enabled(self, db_session, monkeypatch):
        pipeline = MagicMock()
        payload, background_tasks = _create(db_session, monkeypatch, search_on_add=True, pipeline=pipeline)

        assert payload["title"] == "Added Book"
        matching = [t for t in background_tasks.tasks if t.func is pipeline.search_single_book]
        assert len(matching) == 1
        assert matching[0].args == (payload["id"],)

    def test_no_search_when_disabled(self, db_session, monkeypatch):
        pipeline = MagicMock()
        _, background_tasks = _create(db_session, monkeypatch, search_on_add=False, pipeline=pipeline)

        assert background_tasks.tasks == []

    def test_book_created_even_without_pipeline(self, db_session, monkeypatch):
        payload, background_tasks = _create(db_session, monkeypatch, search_on_add=True, pipeline=None)

        assert payload["id"] is not None
        assert background_tasks.tasks == []

    def test_no_search_for_non_searchable_status(self, db_session, monkeypatch):
        pipeline = MagicMock()
        _, background_tasks = _create(
            db_session, monkeypatch, search_on_add=True, pipeline=pipeline, status=BookStatus.IN_LIBRARY.value
        )

        assert background_tasks.tasks == []


class TestCreateBookManualHardcoverId:
    def test_generates_hardcover_id_when_missing(self, db_session, monkeypatch):
        payload, _ = _create(db_session, monkeypatch, search_on_add=False)

        assert payload["hardcover_id"] is not None
        assert payload["hardcover_id"].startswith("manual-")

        from backend.models.book import Book

        book = db_session.get(Book, payload["id"])
        assert book.source == "manual"

    def test_keeps_supplied_hardcover_id(self, db_session, monkeypatch):
        monkeypatch.setattr("backend.api.routes.library.load_config", lambda: _make_config(False))
        request = _make_request()
        background_tasks = BackgroundTasks()
        body = BookCreateRequest(title="Known Book", author_name="Known Author", hardcover_id="hc-123")
        payload = asyncio.run(create_book(body, request, background_tasks, db_session))

        assert payload["hardcover_id"] == "hc-123"
