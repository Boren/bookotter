# pyright: reportGeneralTypeIssues=false

"""
Advisory pipeline lock using SQLite.
Prevents concurrent pipeline runs from interfering with each other.
Only one pipeline run can hold the lock at a time.
Stale locks (> PIPELINE_LOCK_STALE_THRESHOLD_HOURS) are auto-cleared on acquire.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.constants import PIPELINE_LOCK_STALE_THRESHOLD_HOURS
from backend.errors import FailureReason, PipelineError
from backend.models.book import PipelineLock

logger = logging.getLogger(__name__)


def get_active_lock(db: Session) -> PipelineLock | None:
    return db.get(PipelineLock, 1)


@contextmanager
def acquire_pipeline_lock(db: Session, holder: str) -> Generator[str, None, None]:
    """
    Context manager that acquires the single-row advisory pipeline lock.

    Yields the run_id string on success.
    Raises PipelineError(PIPELINE_LOCK_HELD) if lock is fresh (held by another run).
    Auto-clears stale locks (> PIPELINE_LOCK_STALE_THRESHOLD_HOURS old).
    Releases lock on context exit (success or exception).

    Args:
        db: SQLAlchemy session
        holder: "scheduled" | "manual" | "cli"
    """
    now = datetime.utcnow()
    stale_threshold = now - timedelta(hours=PIPELINE_LOCK_STALE_THRESHOLD_HOURS)

    existing = get_active_lock(db)

    if existing is not None:
        if existing.locked_at < stale_threshold:
            logger.warning(
                "Clearing stale pipeline lock held by '%s' since %s",
                existing.holder,
                existing.locked_at.isoformat(),
            )
            db.delete(existing)
            db.flush()
        else:
            raise PipelineError(
                f"Pipeline lock held by '{existing.holder}' (run_id={existing.run_id})",
                FailureReason.PIPELINE_LOCK_HELD,
            )

    run_id = uuid4().hex
    lock = PipelineLock(id=1, locked_at=now, run_id=run_id, holder=holder)
    db.add(lock)
    try:
        db.commit()
    except IntegrityError as e:
        # Race: another caller committed first between our SELECT and INSERT.
        # Convert PK violation into the canonical PIPELINE_LOCK_HELD error.
        db.rollback()
        existing_after = get_active_lock(db)
        holder_str = existing_after.holder if existing_after is not None else "unknown"
        run_id_str = existing_after.run_id if existing_after is not None else "unknown"
        raise PipelineError(
            f"Pipeline lock held by '{holder_str}' (run_id={run_id_str})",
            FailureReason.PIPELINE_LOCK_HELD,
        ) from e

    logger.info("Pipeline lock acquired: run_id=%s holder=%s", run_id, holder)

    try:
        yield run_id
    finally:
        lock_to_delete = get_active_lock(db)
        if lock_to_delete is not None and lock_to_delete.run_id == run_id:
            db.delete(lock_to_delete)
            db.commit()
            logger.info("Pipeline lock released: run_id=%s", run_id)
