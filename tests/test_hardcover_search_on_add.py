# pyright: reportGeneralTypeIssues=false, reportArgumentType=false

"""Tests for auto-search wiring after Hardcover sync (Fix 1)."""

from unittest.mock import MagicMock, call

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


def _make_sync_result(new_books: int = 0, new_book_ids: list[int] | None = None) -> dict:
    if new_book_ids is None:
        new_book_ids = list(range(1, new_books + 1))
    return {
        "new_books": new_books,
        "new_book_ids": new_book_ids,
        "existing_skipped": 0,
        "errors": 0,
    }


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


def _make_app_with_pipeline(
    grabs_per_search: list[int] | None = None, raises: bool = False
) -> FastAPI:
    app = FastAPI()
    pipeline = MagicMock()
    if raises:
        pipeline.search_single_book.side_effect = RuntimeError("Prowlarr down")
    else:
        pipeline.search_single_book.side_effect = grabs_per_search or []
    app.state.pipeline = pipeline
    return app


class TestSearchOnAdd:
    def test_searches_only_new_books_when_enabled(self, monkeypatch):
        config = _make_config(search_on_add=True)
        _apply_patches(
            monkeypatch,
            config=config,
            sync_result=_make_sync_result(new_books=2, new_book_ids=[7, 9]),
        )
        app = _make_app_with_pipeline(grabs_per_search=[1, 0])

        result = _run_hardcover_sync_background(app=app)

        assert app.state.pipeline.search_single_book.call_args_list == [call(7), call(9)]
        app.state.pipeline.process_wanted_books.assert_not_called()
        assert result["new_books"] == 2
        assert result["auto_searched"] == 1

    def test_skips_when_search_on_add_disabled(self, monkeypatch):
        config = _make_config(search_on_add=False)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=2))
        app = _make_app_with_pipeline()

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.search_single_book.assert_not_called()
        app.state.pipeline.process_wanted_books.assert_not_called()
        assert "auto_searched" not in result
        assert "auto_search_error" not in result

    def test_skips_when_no_new_books(self, monkeypatch):
        config = _make_config(search_on_add=True)
        _apply_patches(monkeypatch, config=config, sync_result=_make_sync_result(new_books=0))
        app = _make_app_with_pipeline()

        result = _run_hardcover_sync_background(app=app)

        app.state.pipeline.search_single_book.assert_not_called()
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

    def test_records_error_when_search_raises(self, monkeypatch, caplog):
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

        app.state.pipeline.search_single_book.assert_not_called()
        app.state.pipeline.process_wanted_books.assert_not_called()
        assert result == {"error": "Hardcover API token not configured"}


class TestScheduledPollerDelegation:
    def test_scheduled_sync_delegates_to_shared_helper(self, monkeypatch):
        """The scheduled poller must run the exact same code path as the manual
        sync endpoint, so the two triggers cannot drift apart again."""
        from backend import main as main_module

        calls: list = []

        def fake_helper(app):
            calls.append(app)
            return {"new_books": 0, "new_book_ids": [], "existing_skipped": 0, "errors": 0}

        monkeypatch.setattr(main_module, "_run_hardcover_sync_background", fake_helper)

        app = MagicMock()
        main_module._scheduled_hardcover_sync(app)

        assert calls == [app]
