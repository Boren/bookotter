# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false

"""Tests for pipeline lock guard preventing concurrent run_pipeline executions."""

import tempfile
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.errors import FailureReason, PipelineError
from backend.models import blocklist  # noqa: F401 — registers BlocklistEntry with Base.metadata
from backend.models.book import PipelineLock
from backend.services.pipeline_service import PipelineService
from backend.utils.clock import naive_utcnow
from backend.utils.pipeline_lock import acquire_pipeline_lock, get_active_lock


@pytest.fixture
def shared_db_factory():
    """File-based SQLite session factory shared across connections/threads."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(bind=engine)
        SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        yield SessionFactory
        engine.dispose()


class TestPipelineLockGuard:
    def test_lock_released_on_pipeline_exception(self, db_session):
        """Lock is released even when pipeline raises mid-run."""
        with pytest.raises(RuntimeError):  # noqa: PT012
            with acquire_pipeline_lock(db_session, holder="test"):
                raise RuntimeError("pipeline error")

        assert get_active_lock(db_session) is None

    def test_api_returns_409_when_lock_held(self, db_session):
        """Manual trigger returns 409 when pipeline already running."""
        lock = PipelineLock(
            id=1,
            locked_at=naive_utcnow(),
            run_id="test-run-id",
            holder="scheduled",
        )
        db_session.add(lock)
        db_session.commit()

        active = get_active_lock(db_session)

        assert active is not None
        assert active.holder == "scheduled"
        assert active.run_id == "test-run-id"

        with pytest.raises(PipelineError) as exc_info:  # noqa: PT012
            with acquire_pipeline_lock(db_session, holder="manual"):
                pass
        assert exc_info.value.reason == FailureReason.PIPELINE_LOCK_HELD

    def test_five_concurrent_pipeline_runs_one_succeeds(self, shared_db_factory):
        """5 concurrent run_pipeline calls → exactly 1 succeeds, 4 get lock_held."""
        results: list[dict] = []
        result_lock = threading.Lock()
        barrier = threading.Barrier(5)

        def slow_stage():
            time.sleep(0.3)
            return 0

        def try_run():
            service = PipelineService(db_session_factory=shared_db_factory)
            service.process_grabbed_books = slow_stage
            service.process_downloading_books = slow_stage
            service.process_importing_books = slow_stage
            barrier.wait()
            result = service.run_pipeline(holder="scheduled")
            with result_lock:
                results.append(result)

        threads = [threading.Thread(target=try_run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if not r.get("skipped")]
        skipped = [r for r in results if r.get("skipped")]

        assert len(results) == 5, f"Expected 5 results, got {len(results)}"
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {results}"
        assert len(skipped) == 4, f"Expected 4 skipped, got {len(skipped)}: {results}"
        assert all(r.get("reason") == "lock_held" for r in skipped)

        db = shared_db_factory()
        try:
            assert get_active_lock(db) is None
        finally:
            db.close()
