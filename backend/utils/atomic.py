"""
Atomic file write and copy utilities.
All writes go through a temp file on the same filesystem, then atomic rename.
Guarantees: destination is either fully written or absent; never partial.
"""

import errno
import os
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from backend.errors import FailureReason, PipelineError


@contextmanager
def atomic_write(dest: Path, mode: str = "wb") -> Generator[IO]:
    """
    Context manager for atomic file writes.

    1. Creates temp file in same directory as dest (same filesystem -> atomic rename)
    2. Yields the file handle for the caller to write
    3. On success: fsync the file, close it, rename to dest, fsync parent dir
    4. On exception: unlink temp file, re-raise (dest unchanged)

    Usage:
        with atomic_write(Path("/some/file.epub")) as f:
            f.write(data)
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    tmp_path_obj = Path(tmp_path)

    try:
        with os.fdopen(tmp_fd, mode) as fh:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tmp_path, dest)

        # fsync parent directory to ensure directory entry is durable
        dir_fd = os.open(str(dest.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            tmp_path_obj.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_move(source: Path, dest: Path) -> None:
    """
    Move source to dest without ever overwriting a different file.

    - dest exists and is NOT the same inode as source: raises FileExistsError
      (callers pre-resolve collisions; same-inode permits case-only renames
      on case-insensitive filesystems).
    - Same filesystem: os.replace, then fsync dest parent dir.
    - Cross-device (EXDEV): atomic_copy then unlink source.
    - On OSError ENOSPC: raises PipelineError(IMPORT_DISK_FULL).
    """
    source = Path(source)
    dest = Path(dest)

    if dest.exists() and not dest.samefile(source):
        raise FileExistsError(f"Destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(source, dest)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise PipelineError("No space left on device", FailureReason.IMPORT_DISK_FULL) from exc
        if exc.errno != errno.EXDEV:
            raise
        # Different filesystem: copy atomically, then remove the source.
        atomic_copy(source, dest)
        source.unlink()
        return

    # POSIX quirk: renaming one hard link of a file onto another link of the
    # same file is a no-op, leaving the source entry behind. Check the literal
    # directory listing (not Path.exists(), which would also match the new
    # name case-insensitively) and remove the leftover link.
    if source != dest and source.name in os.listdir(source.parent):
        source.unlink()

    dir_fd = os.open(str(dest.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_copy(source: Path, dest: Path) -> None:
    """
    Atomically copy source to dest.

    Uses atomic_write internally. Preserves mtime/mode via shutil.copystat.
    On OSError ENOSPC: raises PipelineError(IMPORT_DISK_FULL).
    """
    source = Path(source)
    dest = Path(dest)

    try:
        with atomic_write(dest, mode="wb") as fh, source.open("rb") as src:
            shutil.copyfileobj(src, fh)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise PipelineError("No space left on device", FailureReason.IMPORT_DISK_FULL) from exc
        raise

    # Preserve mtime and mode (atomic_write doesn't do this)
    shutil.copystat(source, dest)
