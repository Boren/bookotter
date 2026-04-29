"""Tests for atomic import operations: SIGKILL durability, collision versioning, filename limits."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from backend.constants import MAX_COLLISION_ATTEMPTS, MAX_FILENAME_LENGTH
from backend.errors import FailureReason, PipelineError
from backend.models.book import BookStatus, FolderOrganization
from backend.services.import_service import ImportService, sanitize_path_component
from backend.utils.atomic import atomic_copy
from tests.helpers import create_test_epub
from tests.test_import_service import _make_book, _make_root_folder


def _copy_worker(src_str: str, dest_str: str) -> None:
    """Subprocess target: import_atomic copy that we will SIGKILL mid-flight."""
    from pathlib import Path

    from backend.utils.atomic import atomic_copy

    time.sleep(0.05)
    atomic_copy(Path(src_str), Path(dest_str))


class TestAtomicCopyDurability:
    def test_normal_copy_leaves_no_tmp_files(self, tmp_path: Path) -> None:
        src = tmp_path / "book.epub"
        src.write_bytes(b"epub content")
        dest = tmp_path / "library" / "book.epub"

        atomic_copy(src, dest)

        assert dest.exists()
        assert dest.read_bytes() == b"epub content"
        assert list(tmp_path.glob("**/*.tmp")) == []

    def test_sigkill_during_copy_no_partial_destination(self, tmp_path: Path) -> None:
        src = tmp_path / "large.epub"
        src.write_bytes(b"X" * (5 * 1024 * 1024))
        expected_size = src.stat().st_size

        for attempt in range(5):
            dest = tmp_path / f"output_{attempt}.epub"
            proc = multiprocessing.Process(target=_copy_worker, args=(str(src), str(dest)))
            proc.start()
            time.sleep(0.02)
            proc.kill()
            proc.join(timeout=5)

            if dest.exists():
                actual = dest.stat().st_size
                assert actual == expected_size, f"Partial file detected: expected {expected_size} bytes, got {actual}"

        leftover_tmp = list(tmp_path.glob("**/*.tmp"))
        assert all(t.parent == tmp_path or t.parent.name == "library" for t in leftover_tmp), (
            f"Unexpected tmp leftovers: {leftover_tmp}"
        )

    def test_enospc_raises_pipeline_error_disk_full(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import errno

        src = tmp_path / "src.epub"
        src.write_bytes(b"data")
        dest = tmp_path / "dest.epub"

        from backend.utils import atomic as atomic_module

        original_copyfileobj = atomic_module.shutil.copyfileobj

        def fake_copyfileobj(src_fh, dst_fh, length: int = 16 * 1024) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(atomic_module.shutil, "copyfileobj", fake_copyfileobj)

        with pytest.raises(PipelineError) as exc_info:
            atomic_copy(src, dest)

        assert exc_info.value.reason == FailureReason.IMPORT_DISK_FULL
        assert not dest.exists(), "ENOSPC must leave no partial destination"
        assert list(tmp_path.glob("*.tmp")) == [], "ENOSPC must leave no .tmp files"

        monkeypatch.setattr(atomic_module.shutil, "copyfileobj", original_copyfileobj)


class TestFilenameTruncation:
    def test_short_name_unchanged(self) -> None:
        result = sanitize_path_component("Normal Title")
        assert result == "Normal Title"

    def test_exact_max_length_unchanged(self) -> None:
        name = "A" * MAX_FILENAME_LENGTH
        result = sanitize_path_component(name)
        assert result == name
        assert len(result) == MAX_FILENAME_LENGTH

    def test_oversize_name_truncated_to_max_length(self) -> None:
        long_name = "A" * 250
        result = sanitize_path_component(long_name)
        assert len(result) == MAX_FILENAME_LENGTH

    def test_oversize_name_includes_hash_suffix(self) -> None:
        long_name = "A" * 250
        result = sanitize_path_component(long_name)
        assert result.startswith("A")
        assert "_" in result
        hash_part = result.rsplit("_", 1)[1]
        assert len(hash_part) == 8
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_distinct_long_names_get_distinct_hashes(self) -> None:
        """Two different long names that share a 191-char prefix must produce distinct results."""
        name_a = "A" * 250 + "different_a"
        name_b = "A" * 250 + "different_b"
        result_a = sanitize_path_component(name_a)
        result_b = sanitize_path_component(name_b)
        assert result_a != result_b


class TestCollisionVersioning:
    def _make_source(self, tmp_path: Path) -> Path:
        src = tmp_path / "source.epub"
        create_test_epub(str(src), "Source Book", "Source Author")
        return src

    def test_first_import_uses_unversioned_name(self, db_session, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        lib.mkdir()
        src = self._make_source(tmp_path)
        rf = _make_root_folder(db_session, lib, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Solo Title", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        result = svc.import_book(cast(int, book.id), src)

        assert cast(str | None, result.file_path) == "Solo Title.epub"

    def test_second_import_uses_v1(self, db_session, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        lib.mkdir()
        src = self._make_source(tmp_path)
        rf = _make_root_folder(db_session, lib, FolderOrganization.FLAT.value)
        book1 = _make_book(db_session, rf, title="Same Title", status=BookStatus.DOWNLOADING.value)
        book2 = _make_book(db_session, rf, title="Same Title", status=BookStatus.DOWNLOADING.value)
        svc = ImportService(db_session)

        svc.import_book(cast(int, book1.id), src)
        result = svc.import_book(cast(int, book2.id), src)

        assert cast(str | None, result.file_path) == "Same Title (1).epub"
        assert (lib / "Same Title.epub").exists()
        assert (lib / "Same Title (1).epub").exists()

    def test_third_import_uses_v2(self, db_session, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        lib.mkdir()
        src = self._make_source(tmp_path)
        rf = _make_root_folder(db_session, lib, FolderOrganization.FLAT.value)
        svc = ImportService(db_session)

        for _ in range(3):
            book = _make_book(db_session, rf, title="Triple Title", status=BookStatus.DOWNLOADING.value)
            svc.import_book(cast(int, book.id), src)

        assert (lib / "Triple Title.epub").exists()
        assert (lib / "Triple Title (1).epub").exists()
        assert (lib / "Triple Title (2).epub").exists()

    def test_too_many_collisions_raises_pipeline_error(self, db_session, tmp_path: Path) -> None:
        lib = tmp_path / "library"
        lib.mkdir()
        rf = _make_root_folder(db_session, lib, FolderOrganization.FLAT.value)
        book = _make_book(db_session, rf, title="Crowded", status=BookStatus.DOWNLOADING.value)

        (lib / "Crowded.epub").write_bytes(b"placeholder")
        for i in range(1, MAX_COLLISION_ATTEMPTS + 1):
            (lib / f"Crowded ({i}).epub").write_bytes(b"placeholder")

        mock_epub = MagicMock()
        mock_epub.validate_epub.return_value = True
        svc = ImportService(db_session, epub_service=mock_epub)
        src = self._make_source(tmp_path)

        with pytest.raises(PipelineError) as exc_info:
            svc.import_book(cast(int, book.id), src)

        assert exc_info.value.reason == FailureReason.IMPORT_FILE_COLLISION


class TestCopyToLibraryAtomic:
    def test_copy_to_library_uses_atomic_no_tmp_leftover(self, db_session, tmp_path: Path) -> None:
        src = tmp_path / "src.epub"
        create_test_epub(str(src), "Atomic Test", "Author")
        dest = tmp_path / "library" / "out.epub"

        svc = ImportService(db_session, epub_service=MagicMock())
        svc.copy_to_library(src, dest)

        assert dest.exists()
        assert list((tmp_path / "library").glob("*.tmp")) == []

    def test_copy_to_library_disk_full_raises_pipeline_error(
        self, db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import errno

        src = tmp_path / "src.epub"
        create_test_epub(str(src), "DF Test", "Author")
        dest = tmp_path / "library" / "out.epub"

        from backend.utils import atomic as atomic_module

        def fake_copyfileobj(src_fh, dst_fh, length: int = 16 * 1024) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(atomic_module.shutil, "copyfileobj", fake_copyfileobj)

        svc = ImportService(db_session, epub_service=MagicMock())

        with pytest.raises(PipelineError) as exc_info:
            svc.copy_to_library(src, dest)

        assert exc_info.value.reason == FailureReason.IMPORT_DISK_FULL
        assert not dest.exists()

    def test_copy_to_library_other_oserror_raises_copy_failed(
        self, db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import errno

        src = tmp_path / "src.epub"
        create_test_epub(str(src), "EIO Test", "Author")
        dest = tmp_path / "library" / "out.epub"

        from backend.utils import atomic as atomic_module

        def fake_copyfileobj(src_fh, dst_fh, length: int = 16 * 1024) -> None:
            raise OSError(errno.EIO, "I/O error")

        monkeypatch.setattr(atomic_module.shutil, "copyfileobj", fake_copyfileobj)

        svc = ImportService(db_session, epub_service=MagicMock())

        with pytest.raises(PipelineError) as exc_info:
            svc.copy_to_library(src, dest)

        assert exc_info.value.reason == FailureReason.IMPORT_COPY_FAILED
