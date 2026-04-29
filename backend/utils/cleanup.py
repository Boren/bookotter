"""Cleanup utilities for orphaned temporary files."""

import logging
import time
from pathlib import Path

from backend.constants import TMP_FILE_MAX_AGE_HOURS

logger = logging.getLogger(__name__)


def cleanup_orphan_tmp_files(
    root_dirs: list[Path],
    max_age_hours: int = TMP_FILE_MAX_AGE_HOURS,
) -> int:
    """
    Walk root_dirs and delete *.tmp files older than max_age_hours.
    Returns count of deleted files.
    """
    deleted = 0
    cutoff_seconds = max_age_hours * 3600
    now = time.time()

    for root_dir in root_dirs:
        if not root_dir.exists():
            continue
        for path in root_dir.rglob("*.tmp"):
            try:
                age = now - path.stat().st_mtime
                if age > cutoff_seconds:
                    path.unlink()
                    logger.info("Deleted orphan tmp file: %s (age=%.1fh)", path, age / 3600)
                    deleted += 1
            except OSError as exc:
                logger.warning("Could not delete %s: %s", path, exc)

    return deleted
