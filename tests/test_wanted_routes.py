import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from backend.api.routes.wanted import list_missing_books, search_all_missing
from backend.models.book import BookStatus
from tests.helpers import create_test_book


def _make_request(pipeline=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pipeline=pipeline)))


class TestListMissingBooks:
    def test_returns_missing_books(self, db_session):
        create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
        db_session.commit()

        payload = asyncio.run(list_missing_books(db_session))

        assert payload["total"] == 1
        assert payload["books"][0]["title"] == "Missing Book"
        assert payload["books"][0]["status"] == BookStatus.MISSING.value

    def test_excludes_non_missing_books(self, db_session):
        create_test_book(db_session, title="Missing Book", status=BookStatus.MISSING)
        create_test_book(db_session, title="Wanted Book", status=BookStatus.WANTED)
        create_test_book(db_session, title="Library Book", status=BookStatus.IN_LIBRARY)
        db_session.commit()

        payload = asyncio.run(list_missing_books(db_session))

        assert payload["total"] == 1
        assert [book["title"] for book in payload["books"]] == ["Missing Book"]


class TestSearchAllMissing:
    def test_returns_503_when_pipeline_not_configured(self, db_session):
        request = _make_request(pipeline=None)
        background_tasks = BackgroundTasks()

        with pytest.raises(HTTPException) as exc:
            asyncio.run(search_all_missing(request, background_tasks, db_session))

        assert exc.value.status_code == 503

    def test_queues_background_search_for_wanted_and_missing(self, db_session):
        create_test_book(db_session, title="Missing One", status=BookStatus.MISSING)
        create_test_book(db_session, title="Missing Two", status=BookStatus.MISSING)
        create_test_book(db_session, title="Wanted Book", status=BookStatus.WANTED)
        create_test_book(db_session, title="In Library", status=BookStatus.IN_LIBRARY)
        db_session.commit()

        pipeline = MagicMock()
        request = _make_request(pipeline=pipeline)
        background_tasks = BackgroundTasks()

        payload = asyncio.run(search_all_missing(request, background_tasks, db_session))

        assert payload["queued"] == 3
        assert any(task.func is pipeline.process_wanted_books for task in background_tasks.tasks)

    def test_zero_pending_does_not_schedule_task(self, db_session):
        create_test_book(db_session, title="In Library", status=BookStatus.IN_LIBRARY)
        db_session.commit()

        pipeline = MagicMock()
        request = _make_request(pipeline=pipeline)
        background_tasks = BackgroundTasks()

        payload = asyncio.run(search_all_missing(request, background_tasks, db_session))

        assert payload["queued"] == 0
        assert background_tasks.tasks == []
