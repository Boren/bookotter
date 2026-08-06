"""Tests for the automatic Kindle sync: scheduled-run wrapper and job registration."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.api.routes.config as config_routes
import backend.api.routes.sync as sync_routes
from backend.main import app
from backend.services.scheduler_service import SchedulerService

KINDLE_CONFIG = {
    "id": "abc123",
    "name": "My Kindle",
    "hostname": "kindle.local",
    "port": 22,
    "username": "root",
    "password": "",
    "ssh_key_path": "",
    "destination_path": "/mnt/us/books/",
}


@pytest.fixture
def client():
    yield TestClient(app)


@pytest.fixture(autouse=True)
def reset_sync_flag():
    sync_routes._kindle_sync_running = False
    yield
    sync_routes._kindle_sync_running = False


@pytest.fixture
def fresh_scheduler():
    """Isolated SchedulerService so tests never touch the global singleton's jobs."""
    service = SchedulerService()
    with patch("backend.services.scheduler_service.scheduler", service):
        yield service


class TestRunScheduledKindleSync:
    def test_skips_when_no_kindle_configured(self):
        background = MagicMock()
        with (
            patch.object(sync_routes, "get_first_real_kindle", return_value=None),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
        ):
            result = sync_routes._run_scheduled_kindle_sync()

        assert result == {"skipped": "no_kindle"}
        background.assert_not_called()
        assert sync_routes._kindle_sync_running is False

    def test_skips_when_sync_already_running_and_keeps_flag(self):
        sync_routes._kindle_sync_running = True
        background = MagicMock()
        with (
            patch.object(sync_routes, "get_first_real_kindle", return_value=KINDLE_CONFIG),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
        ):
            result = sync_routes._run_scheduled_kindle_sync()

        assert result == {"skipped": "already_running"}
        background.assert_not_called()
        # Must not clear the flag out from under the in-flight sync
        assert sync_routes._kindle_sync_running is True

    def test_skips_when_kindle_offline_and_clears_flag(self):
        background = MagicMock()
        with (
            patch.object(sync_routes, "get_first_real_kindle", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=False),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
        ):
            result = sync_routes._run_scheduled_kindle_sync()

        assert result == {"skipped": "kindle_offline"}
        background.assert_not_called()
        assert sync_routes._kindle_sync_running is False

    def test_reachable_kindle_runs_sync_with_scheduled_trigger(self):
        flag_during_call = []

        def record_flag(**kwargs):
            flag_during_call.append(sync_routes._kindle_sync_running)
            return {"transferred": 1}

        background = MagicMock(side_effect=record_flag)
        with (
            patch.object(sync_routes, "get_first_real_kindle", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=True),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
            patch.object(sync_routes, "load_config", return_value={}),
        ):
            result = sync_routes._run_scheduled_kindle_sync()

        assert result == {"transferred": 1}
        background.assert_called_once_with(kindle_device="abc123", dry_run=False, trigger_type="scheduled")
        # Guard flag was held while the sync ran
        assert flag_during_call == [True]

    def test_global_dry_run_config_is_respected(self):
        background = MagicMock(return_value={"dry_run": True})
        with (
            patch.object(sync_routes, "get_first_real_kindle", return_value=KINDLE_CONFIG),
            patch.object(sync_routes.KindleClient, "is_reachable", return_value=True),
            patch.object(sync_routes, "_run_kindle_sync_background", background),
            patch.object(sync_routes, "load_config", return_value={"transfer": {"dry_run": True}}),
        ):
            sync_routes._run_scheduled_kindle_sync()

        background.assert_called_once_with(kindle_device="abc123", dry_run=True, trigger_type="scheduled")


class TestApplyKindleSyncSchedule:
    def test_enabled_registers_interval_job(self, fresh_scheduler):
        sync_routes.apply_kindle_sync_schedule({"kindle_sync": {"enabled": True, "interval_hours": 6}})

        job = fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID)
        assert job is not None
        assert job.trigger.interval == timedelta(hours=6)

    def test_disabled_removes_existing_job(self, fresh_scheduler):
        sync_routes.apply_kindle_sync_schedule({"kindle_sync": {"enabled": True, "interval_hours": 1}})
        assert fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID) is not None

        sync_routes.apply_kindle_sync_schedule({"kindle_sync": {"enabled": False, "interval_hours": 1}})
        assert fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID) is None

    def test_disabled_with_no_job_is_a_noop(self, fresh_scheduler):
        sync_routes.apply_kindle_sync_schedule({"kindle_sync": {"enabled": False}})
        assert fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID) is None

    def test_invalid_interval_falls_back_to_hourly(self, fresh_scheduler):
        sync_routes.apply_kindle_sync_schedule({"kindle_sync": {"enabled": True, "interval_hours": 5}})

        job = fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID)
        assert job.trigger.interval == timedelta(hours=1)

    def test_missing_section_means_disabled(self, fresh_scheduler):
        sync_routes.apply_kindle_sync_schedule({})
        assert fresh_scheduler.scheduler.get_job(sync_routes.KINDLE_SYNC_JOB_ID) is None


class TestConfigUpdateReschedules:
    def test_put_with_kindle_sync_section_applies_schedule(self, client):
        updated = {"kindle_sync": {"enabled": True, "interval_hours": 1}}
        with (
            patch.object(config_routes, "update_config", return_value=updated),
            patch("backend.api.routes.sync.apply_kindle_sync_schedule") as apply_mock,
        ):
            response = client.put("/api/config", json={"config": updated})

        assert response.status_code == 200
        apply_mock.assert_called_once_with(updated)

    def test_put_without_kindle_sync_section_does_not_touch_scheduler(self, client):
        with (
            patch.object(config_routes, "update_config", return_value={"logging": {}}),
            patch("backend.api.routes.sync.apply_kindle_sync_schedule") as apply_mock,
        ):
            response = client.put("/api/config", json={"config": {"logging": {"log_level": "INFO"}}})

        assert response.status_code == 200
        apply_mock.assert_not_called()
