import errno
import multiprocessing
import os
import time
from unittest.mock import patch

import pytest

from backend.errors import FailureReason, PipelineError
from backend.utils.atomic import atomic_copy, atomic_move, atomic_write


class TestAtomicWrite:
    def test_success_no_tmp_leftover(self, tmp_path):
        dest = tmp_path / "output.epub"
        with atomic_write(dest) as f:
            f.write(b"hello world")
        assert dest.exists()
        assert dest.read_bytes() == b"hello world"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_exception_no_dest_no_tmp(self, tmp_path):
        dest = tmp_path / "output.epub"
        with pytest.raises(ValueError):  # noqa: PT012
            with atomic_write(dest) as f:
                f.write(b"partial")
                raise ValueError("oops")
        assert not dest.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_creates_parent_dir(self, tmp_path):
        dest = tmp_path / "nested" / "deep" / "file.epub"
        with atomic_write(dest) as f:
            f.write(b"data")
        assert dest.exists()
        assert dest.read_bytes() == b"data"

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "output.epub"
        dest.write_bytes(b"old")
        with atomic_write(dest) as f:
            f.write(b"new")
        assert dest.read_bytes() == b"new"
        assert list(tmp_path.glob("*.tmp")) == []


class TestAtomicCopy:
    def test_success_preserves_content(self, tmp_path):
        src = tmp_path / "source.epub"
        src.write_bytes(b"epub content here")
        dest = tmp_path / "dest.epub"

        atomic_copy(src, dest)

        assert dest.read_bytes() == b"epub content here"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_preserves_mtime(self, tmp_path):
        src = tmp_path / "source.epub"
        src.write_bytes(b"data")
        past_mtime = time.time() - 3600
        os.utime(src, (past_mtime, past_mtime))

        dest = tmp_path / "dest.epub"
        atomic_copy(src, dest)

        assert abs(dest.stat().st_mtime - src.stat().st_mtime) < 1.0

    def test_enospc_raises_import_disk_full(self, tmp_path):
        src = tmp_path / "source.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "dest.epub"

        enospc = OSError(errno.ENOSPC, "No space left on device")
        with patch("backend.utils.atomic.shutil.copyfileobj", side_effect=enospc):
            with pytest.raises(PipelineError) as exc_info:
                atomic_copy(src, dest)

        assert exc_info.value.reason == FailureReason.IMPORT_DISK_FULL
        assert not dest.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_other_oserror_propagates(self, tmp_path):
        src = tmp_path / "source.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "dest.epub"

        eio = OSError(errno.EIO, "I/O error")
        with patch("backend.utils.atomic.shutil.copyfileobj", side_effect=eio):
            with pytest.raises(OSError) as exc_info:
                atomic_copy(src, dest)

        assert exc_info.value.errno == errno.EIO
        assert not isinstance(exc_info.value, PipelineError)
        assert not dest.exists()


class TestAtomicMove:
    def test_moves_file(self, tmp_path):
        src = tmp_path / "old name.epub"
        src.write_bytes(b"epub content")
        dest = tmp_path / "New Name.epub"

        atomic_move(src, dest)

        assert dest.read_bytes() == b"epub content"
        assert not src.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_creates_parent_dir(self, tmp_path):
        src = tmp_path / "book.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "Author" / "Series" / "book.epub"

        atomic_move(src, dest)

        assert dest.read_bytes() == b"data"
        assert not src.exists()

    def test_dest_exists_raises(self, tmp_path):
        src = tmp_path / "a.epub"
        src.write_bytes(b"aaa")
        dest = tmp_path / "b.epub"
        dest.write_bytes(b"bbb")

        with pytest.raises(FileExistsError):
            atomic_move(src, dest)

        assert src.read_bytes() == b"aaa"
        assert dest.read_bytes() == b"bbb"

    def test_same_inode_dest_allowed(self, tmp_path):
        # Proxy for case-only renames on case-insensitive filesystems (APFS):
        # dest "exists" but is the same file as source.
        src = tmp_path / "book.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "Book (2).epub"
        os.link(src, dest)

        atomic_move(src, dest)

        assert dest.read_bytes() == b"data"
        assert not src.exists()

    def test_exdev_falls_back_to_copy(self, tmp_path):
        src = tmp_path / "src.epub"
        src.write_bytes(b"cross-device content")
        dest = tmp_path / "dest.epub"

        real_replace = os.replace

        def fake_replace(a, b):
            if str(a) == str(src):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(a, b)

        with patch("backend.utils.atomic.os.replace", side_effect=fake_replace):
            atomic_move(src, dest)

        assert dest.read_bytes() == b"cross-device content"
        assert not src.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_enospc_during_fallback_raises_disk_full(self, tmp_path):
        src = tmp_path / "src.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "dest.epub"

        exdev = OSError(errno.EXDEV, "Invalid cross-device link")
        enospc = OSError(errno.ENOSPC, "No space left on device")
        with patch("backend.utils.atomic.os.replace", side_effect=exdev):
            with patch("backend.utils.atomic.shutil.copyfileobj", side_effect=enospc):
                with pytest.raises(PipelineError) as exc_info:
                    atomic_move(src, dest)

        assert exc_info.value.reason == FailureReason.IMPORT_DISK_FULL
        assert src.exists()  # source untouched on failure
        assert not dest.exists()


def _copy_worker(src_str: str, dest_str: str) -> None:
    """Worker for SIGKILL test — must be top-level for multiprocessing pickling."""
    from pathlib import Path

    from backend.utils.atomic import atomic_copy

    atomic_copy(Path(src_str), Path(dest_str))


class TestSigkillSafety:
    def test_sigkill_during_copy_no_partial(self, tmp_path):
        src = tmp_path / "large.bin"
        src.write_bytes(b"X" * (10 * 1024 * 1024))
        src_size = src.stat().st_size

        for i in range(5):
            dest_iter = tmp_path / f"iter_{i}.bin"
            proc = multiprocessing.Process(target=_copy_worker, args=(str(src), str(dest_iter)))
            proc.start()
            time.sleep(0.005)
            proc.kill()
            proc.join(timeout=5)

            if dest_iter.exists():
                assert dest_iter.stat().st_size == src_size, (
                    f"Partial file found after SIGKILL on iteration {i}: {dest_iter.stat().st_size} vs {src_size}"
                )

        leftover_tmps = list(tmp_path.glob("*.tmp"))
        for tmp_file in leftover_tmps:
            try:
                tmp_file.unlink()
            except OSError:
                pass
