"""Tests for orphan tmp file cleanup."""

import os
import time

from backend.utils.cleanup import cleanup_orphan_tmp_files


class TestCleanupOrphanTmpFiles:
    def test_old_tmp_deleted(self, tmp_path):
        """Old .tmp file (> 1h) is deleted."""
        old_tmp = tmp_path / "old.epub.tmp"
        old_tmp.write_bytes(b"old content")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(old_tmp, (old_time, old_time))

        count = cleanup_orphan_tmp_files([tmp_path], max_age_hours=1)

        assert count == 1
        assert not old_tmp.exists()

    def test_fresh_tmp_preserved(self, tmp_path):
        """Fresh .tmp file (< 1h) is NOT deleted."""
        fresh_tmp = tmp_path / "fresh.epub.tmp"
        fresh_tmp.write_bytes(b"fresh content")
        # mtime is now (default)

        count = cleanup_orphan_tmp_files([tmp_path], max_age_hours=1)

        assert count == 0
        assert fresh_tmp.exists()

    def test_non_tmp_file_never_deleted(self, tmp_path):
        """Non-.tmp file is never deleted regardless of age."""
        epub = tmp_path / "book.epub"
        epub.write_bytes(b"epub content")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(epub, (old_time, old_time))

        count = cleanup_orphan_tmp_files([tmp_path], max_age_hours=1)

        assert count == 0
        assert epub.exists()

    def test_cleanup_idempotent(self, tmp_path):
        """Running cleanup twice → second run deletes 0."""
        old_tmp = tmp_path / "old.tmp"
        old_tmp.write_bytes(b"old")
        old_time = time.time() - 7200
        os.utime(old_tmp, (old_time, old_time))

        count1 = cleanup_orphan_tmp_files([tmp_path], max_age_hours=1)
        count2 = cleanup_orphan_tmp_files([tmp_path], max_age_hours=1)

        assert count1 == 1
        assert count2 == 0
