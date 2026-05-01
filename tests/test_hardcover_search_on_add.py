# pyright: reportGeneralTypeIssues=false, reportArgumentType=false

"""Tests for auto-search wiring after Hardcover sync (Fix 1)."""

from unittest.mock import MagicMock

from fastapi import FastAPI

from backend.api.routes.sync import _run_hardcover_sync_background


def _make_config(search_on_add: bool = True, with_token: bool = True) -> dict:
    return {
        "hardcover": {
            "api_token": "test_token" if with_token else "",
            "api_url": "https://api.hardcover.app/v1/graphql",
        },
        "pipeline": {"search_on_add": search_on_add},
        "sync": {"include_statuses": {"want_to_read": True}},
    }


def _make_sync_result(new_books: int = 0) -> dict:
    return {"new_books": new_books, "existing_skipped": 0, "errors": 0}


def _apply_patches(monkeypatch, *, config: dict, sync_result: dict):
    monkeypatch.setattr("backend.api.routes.sync.load_config", lambda: config)
    monkeypatch.setattr("backend.api.routes.sync.SessionLocal", MagicMock(return_value=MagicMock()))

    mock_client_cls = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("backend.api.routes.sync.HardcoverClient", mock_client_cls)

    mock_service = MagicMock()
    mock_service.sync_hardcover_lists.return_value = sync_result
    mock_service_cls = MagicMock(return_value=mock_service)
    monkeypatch.setattr("backend.api.routes.sync.HardcoverSyncService", mock_service_cls)

    return mock_service


def _make_app_with_pipeline(grabbed_count: int = 0, raises: bool = False) -> FastAPI:
    app = FastAPI()
    pipeline = MagicMock()
    if raises:
        pipeline.process_wanted_books.side_effect = RuntimeError("Prowlarr down")
    else:
        pipeline.process_wanted_books.return_value = grabbed_count
    app.state.pipeline = pipeline
    return app


class TestSearchOnAdd:
    def test_triggers_pipeline_when_enabled_and_new_books(self, monkeypatch):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))
        app = _make_app_with_pipeline(grabbed_count=1)

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.process_wanted_books.assert_called_once_with()
        assert result["new_books"] == 2
        assert result["auto_searched"] == 1

    def test_skips_when_search_on_add_disabled(self, monkeypatch):
        config = _make_config(search_on_add=False)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))
        app = _make_app_with_pipeline()

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.process_wanted_books.assert_not_called()
        assert "auto_searched" not in result
        assert "auto_search_error" not in result

    def test_skips_when_no_new_books(self, monkeypatch):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=0))
        app = _make_app_with_pipeline()

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.process_wanted_books.assert_not_called()
        assert "auto_searched" not in result

    def test_warns_when_pipeline_uninitialized(self, monkeypatch, caplog):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))
        app = FastAPI()

        with caplog.at_level("WARNING"):
            result = _run_hardcover_sync_background(app=app)

        assert result["new_books"] == 2
        assert "auto_searched" not in result
        assert "auto_search_error" not in result
        assert any("pipeline service is not initialized" in record.message for record in caplog.records)

    def test_records_error_when_pipeline_raises(self, monkeypatch, caplog):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))
        app = _make_app_with_pipeline(raises=True)

        with caplog.at_level("ERROR"):
            result = _run_hardcover_sync_background(app=app)

        assert result["new_books"] == 2
        assert "auto_searched" not in result
        assert result["auto_search_error"] == "Prowlarr down"

    def test_no_pipeline_call_when_app_is_none(self, monkeypatch):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))

        result = _run_hardcover_sync_background(app=None)

        assert result["new_books"] == 2
        assert "auto_searched" not in result

    def test_returns_error_early_when_token_missing(self, monkeypatch):
        config = _make_config(search_on_add=True, with_token=False)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=0))
        app = _make_app_with_pipeline()

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.process_wanted_books.assert_not_called()
        assert result == {"error": "Hardcover API token not configured"}
