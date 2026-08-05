# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false

"""Tests for backend.utils.pipeline_lock."""

import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.errors import FailureReason, PipelineError
from backend.models.book import PipelineLock
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


class TestAcquirePipelineLock:
    def test_acquire_when_no_lock(self, db_session):
        with acquire_pipeline_lock(db_session, holder="scheduled") as run_id:
            assert run_id is not None
            lock = get_active_lock(db_session)
            assert lock is not None
            assert lock.holder == "scheduled"
            assert lock.run_id == run_id

    def test_lock_released_on_context_exit_success(self, db_session):
        with acquire_pipeline_lock(db_session, holder="manual"):
            pass
        assert get_active_lock(db_session) is None

    def test_lock_released_on_context_exit_exception(self, db_session):
        with pytest.raises(RuntimeError):  # noqa: PT012
            with acquire_pipeline_lock(db_session, holder="manual"):
                raise RuntimeError("pipeline error")
        assert get_active_lock(db_session) is None

    def test_acquire_when_fresh_lock_held_raises(self, shared_db_factory):
        db1 = shared_db_factory()
        db2 = shared_db_factory()
        try:
            with acquire_pipeline_lock(db1, holder="scheduled"):
                with pytest.raises(PipelineError) as exc_info:  # noqa: PT012
                    with acquire_pipeline_lock(db2, holder="manual"):
                        pass
                assert exc_info.value.reason == FailureReason.PIPELINE_LOCK_HELD
        finally:
            db1.close()
            db2.close()

    def test_stale_lock_replaced(self, db_session):
        stale_time = datetime.utcnow() - timedelta(hours=2)
        stale_lock = PipelineLock(id=1, locked_at=stale_time, run_id="old-run", holder="scheduled")
        db_session.add(stale_lock)
        db_session.commit()

        with acquire_pipeline_lock(db_session, holder="manual") as run_id:
            assert run_id != "old-run"
            lock = get_active_lock(db_session)
            assert lock is not None
            assert lock.holder == "manual"

        assert get_active_lock(db_session) is None

    def test_five_concurrent_one_wins(self, shared_db_factory):
        results: list[str] = []
        errors: list[FailureReason] = []
        result_lock = threading.Lock()
        barrier = threading.Barrier(5)
        # The winner must hold the lock until every loser has attempted;
        # a fixed sleep lets a slow-to-schedule thread acquire after release
        # and turn "exactly one wins" into two.
        all_losers_failed = threading.Event()

        def try_acquire():
            db = shared_db_factory()
            try:
                barrier.wait()
                with acquire_pipeline_lock(db, holder="scheduled"):
                    with result_lock:
                        results.append("success")
                    all_losers_failed.wait(timeout=10)
            except PipelineError as e:
                with result_lock:
                    errors.append(e.reason)
                    if len(errors) == 4:
                        all_losers_failed.set()
            finally:
                db.close()

        threads = [threading.Thread(target=try_acquire) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1, f"Expected 1 success, got {len(results)}"
        assert len(errors) == 4, f"Expected 4 failures, got {len(errors)}"
        assert all(r == FailureReason.PIPELINE_LOCK_HELD for r in errors)
