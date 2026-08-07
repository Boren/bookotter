"""Tests for the library rename API routes and naming-template config validation."""

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api.routes.config import ConfigUpdate, update_config_endpoint
from backend.api.routes.library import RenameApplyRequest, rename_apply, rename_preview
from backend.models.book import BookStatus, FolderOrganization, PipelineLock
from backend.utils.clock import naive_utcnow
from tests.test_import_service import _make_book, _make_root_folder


@pytest.fixture(autouse=True)
def _fixed_template(monkeypatch):
    monkeypatch.setattr(
        "backend.services.rename_service.load_config",
        lambda: {"library": {"naming_template": "{Author} - {Title}"}},
    )
    monkeypatch.setattr("backend.services.rename_service.get_first_real_ereader", lambda config=None: None)
    monkeypatch.setattr("backend.services.rename_service.get_ereader_sync_shelves", lambda config=None: set())


def _seed_book(db, tmp_path, rel_path: str, *, title: str, author_name: str):
    rf = _make_root_folder(db, tmp_path, FolderOrganization.FLAT.value)
    book = _make_book(db, rf, title=title, author_name=author_name, status=BookStatus.IN_LIBRARY.value)
    book.file_path = rel_path
    (Path(rf.path) / rel_path).write_bytes(b"data")
    db.flush()
    return book


class TestRenamePreviewRoute:
    def test_preview_shape(self, db_session, tmp_path):
        _seed_book(db_session, tmp_path, "messy.epub", title="Solaris", author_name="Stanislaw Lem")

        payload = asyncio.run(rename_preview(db_session))

        assert payload["total"] == 1
        assert payload["changed_count"] == 1
        item = payload["items"][0]
        assert item["old_path"] == "messy.epub"
        assert item["new_path"] == "Stanislaw Lem - Solaris.epub"
        assert item["changed"] is True


class TestRenameApplyRoute:
    def test_apply_returns_result(self, db_session, tmp_path):
        _seed_book(db_session, tmp_path, "messy.epub", title="Solaris", author_name="Stanislaw Lem")

        payload = asyncio.run(rename_apply(RenameApplyRequest(), db_session))

        assert payload["renamed"] == 1
        assert (tmp_path / "Stanislaw Lem - Solaris.epub").exists()

    def test_lock_held_returns_409(self, db_session, tmp_path):
        _seed_book(db_session, tmp_path, "messy.epub", title="Solaris", author_name="Stanislaw Lem")
        db_session.add(PipelineLock(id=1, locked_at=naive_utcnow(), run_id="other", holder="scheduled"))
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            asyncio.run(rename_apply(RenameApplyRequest(), db_session))

        assert exc.value.status_code == 409


class TestConfigTemplateValidation:
    def test_invalid_template_rejected_with_422(self):
        body = ConfigUpdate(config={"library": {"naming_template": "{Bogus}"}})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(update_config_endpoint(body))

        assert exc.value.status_code == 422

    def test_missing_title_rejected_with_422(self):
        body = ConfigUpdate(config={"library": {"naming_template": "{Author} only"}})

        with pytest.raises(HTTPException) as exc:
            asyncio.run(update_config_endpoint(body))

        assert exc.value.status_code == 422
