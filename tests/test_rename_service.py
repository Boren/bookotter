"""Tests for backend.services.rename_service — bulk library renaming."""

from pathlib import Path

import pytest

from backend.errors import FailureReason, PipelineError
from backend.models.book import (
    BookStatus,
    FolderOrganization,
    KindleDeliveryStatus,
    PipelineLock,
    RootFolder,
)
from backend.models.scanner import (
    DismissedScanPath,
    MatchProposal,
    MatchProposalStatus,
    Scan,
)
from backend.services.rename_service import RenameService
from backend.utils.clock import naive_utcnow
from tests.test_import_service import _make_book, _make_root_folder

TEMPLATE = "{Author} - {Title}"


@pytest.fixture(autouse=True)
def _fixed_template(monkeypatch):
    monkeypatch.setattr(
        "backend.services.rename_service.load_config",
        lambda: {"library": {"naming_template": TEMPLATE}},
    )


@pytest.fixture(autouse=True)
def _no_kindle(monkeypatch):
    """Default: no real Kindle configured; individual tests override."""
    monkeypatch.setattr("backend.services.rename_service.get_first_real_kindle", lambda config=None: None)
    monkeypatch.setattr("backend.services.rename_service.get_kindle_sync_shelves", lambda config=None: set())


def _library_book(
    db,
    rf: RootFolder,
    rel_path: str,
    *,
    title: str,
    author_name: str,
    content: bytes = b"epub bytes",
    **kwargs,
):
    """Create an IN_LIBRARY book whose file exists at rel_path under rf."""
    book = _make_book(
        db,
        rf,
        title=title,
        author_name=author_name,
        status=BookStatus.IN_LIBRARY.value,
        **kwargs,
    )
    book.file_path = rel_path
    abs_path = Path(rf.path) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    db.flush()
    return book


class TestPreview:
    def test_changed_and_unchanged_items(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        messy = _library_book(db_session, rf, "messy-file.epub", title="Solaris", author_name="Stanislaw Lem")
        _library_book(db_session, rf, "Jane Doe - Clean.epub", title="Clean", author_name="Jane Doe")

        items = RenameService(db_session).preview()

        by_id = {i.book_id: i for i in items}
        assert len(items) == 2
        assert by_id[messy.id].changed is True
        assert by_id[messy.id].old_path == "messy-file.epub"
        assert by_id[messy.id].new_path == "Stanislaw Lem - Solaris.epub"
        assert [i for i in items if not i.changed][0].new_path == "Jane Doe - Clean.epub"

    def test_duplicate_targets_get_suffix(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        first = _library_book(db_session, rf, "a.epub", title="Same", author_name="Same Author")
        second = _library_book(db_session, rf, "b.epub", title="Same", author_name="Other Author")
        second.author_id = first.author_id  # same author + title -> identical rendered name
        db_session.flush()
        db_session.expire(second)

        items = RenameService(db_session).preview()

        new_paths = sorted(i.new_path for i in items)
        assert new_paths == ["Same Author - Same (1).epub", "Same Author - Same.epub"]

    def test_missing_source_flagged(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _library_book(db_session, rf, "ghost.epub", title="Ghost", author_name="No One")
        (tmp_path / "ghost.epub").unlink()

        items = RenameService(db_session).preview()

        assert items[0].book_id == book.id
        assert items[0].error == "source_missing"

    def test_only_in_library_books_considered(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        _make_book(db_session, rf, title="Wanted Book", status=BookStatus.WANTED.value)

        assert RenameService(db_session).preview() == []


class TestApply:
    def test_moves_file_and_updates_db(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        book = _library_book(
            db_session, rf, "messy.epub", title="Solaris", author_name="Stanislaw Lem", content=b"solaris"
        )

        result = RenameService(db_session).apply()

        assert result["renamed"] == 1
        assert result["failed"] == 0
        assert not (tmp_path / "messy.epub").exists()
        assert (tmp_path / "Stanislaw Lem - Solaris.epub").read_bytes() == b"solaris"
        db_session.refresh(book)
        assert book.file_path == "Stanislaw Lem - Solaris.epub"

    def test_idempotent(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        _library_book(db_session, rf, "messy.epub", title="Solaris", author_name="Stanislaw Lem")

        first = RenameService(db_session).apply()
        second = RenameService(db_session).apply()

        assert first["renamed"] == 1
        assert second["renamed"] == 0

    def test_continues_after_single_failure(self, db_session, tmp_path, monkeypatch):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        bad = _library_book(db_session, rf, "bad.epub", title="Bad", author_name="Author A")
        good = _library_book(db_session, rf, "good.epub", title="Good", author_name="Author B")

        import backend.services.rename_service as rs

        real_move = rs.atomic_move

        def flaky_move(source, dest):
            if source.name == "bad.epub":
                raise OSError("simulated failure")
            return real_move(source, dest)

        monkeypatch.setattr(rs, "atomic_move", flaky_move)

        result = RenameService(db_session).apply()

        assert result["failed"] == 1
        assert result["renamed"] == 1
        assert (tmp_path / "Author B - Good.epub").exists()
        db_session.refresh(bad)
        db_session.refresh(good)
        assert bad.file_path == "bad.epub"
        assert good.file_path == "Author B - Good.epub"

    def test_prunes_empty_directories(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        _library_book(db_session, rf, "Old Dir/nested.epub", title="Nested", author_name="Author C")

        RenameService(db_session).apply()

        assert (tmp_path / "Author C - Nested.epub").exists()
        assert not (tmp_path / "Old Dir").exists()
        assert tmp_path.exists()

    def test_book_ids_filter(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        first = _library_book(db_session, rf, "one.epub", title="One", author_name="Author D")
        _library_book(db_session, rf, "two.epub", title="Two", author_name="Author E")

        result = RenameService(db_session).apply(book_ids=[first.id])

        assert result["renamed"] == 1
        assert (tmp_path / "Author D - One.epub").exists()
        assert (tmp_path / "two.epub").exists()

    def test_lock_held_raises(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        _library_book(db_session, rf, "messy.epub", title="Solaris", author_name="Stanislaw Lem")
        db_session.add(PipelineLock(id=1, locked_at=naive_utcnow(), run_id="other", holder="scheduled"))
        db_session.commit()

        with pytest.raises(PipelineError) as exc_info:
            RenameService(db_session).apply()

        assert exc_info.value.reason == FailureReason.PIPELINE_LOCK_HELD
        assert (tmp_path / "messy.epub").exists()

    def test_scanner_tables_updated(self, db_session, tmp_path):
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        _library_book(db_session, rf, "messy.epub", title="Solaris", author_name="Stanislaw Lem")
        scan = Scan(root_folder_id=rf.id)
        db_session.add(scan)
        db_session.flush()
        proposal = MatchProposal(
            scan_id=scan.id,
            root_folder_id=rf.id,
            relative_path="messy.epub",
            file_size=10,
            status=MatchProposalStatus.PENDING.value,
        )
        dismissed_new = DismissedScanPath(root_folder_id=rf.id, relative_path="Stanislaw Lem - Solaris.epub")
        db_session.add_all([proposal, dismissed_new])
        db_session.commit()

        RenameService(db_session).apply()

        db_session.refresh(proposal)
        assert proposal.status == MatchProposalStatus.SUPERSEDED.value
        assert (
            db_session.query(DismissedScanPath)
            .filter_by(root_folder_id=rf.id, relative_path="Stanislaw Lem - Solaris.epub")
            .count()
            == 0
        )

    def test_kindle_delivered_mirror_book_reset(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.services.rename_service.get_first_real_kindle",
            lambda config=None: {"id": "k1", "hostname": "kindle.local"},
        )
        monkeypatch.setattr(
            "backend.services.rename_service.get_kindle_sync_shelves",
            lambda config=None: {"want_to_read"},
        )
        rf = _make_root_folder(db_session, tmp_path, FolderOrganization.FLAT.value)
        mirror = _library_book(db_session, rf, "m.epub", title="Mirror", author_name="Author F")
        mirror.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
        mirror.kindle_delivery_attempts = 3
        mirror.hardcover_status = "want_to_read"
        other = _library_book(db_session, rf, "o.epub", title="Other", author_name="Author G")
        other.kindle_delivery_status = KindleDeliveryStatus.DELIVERED.value
        other.hardcover_status = "read"
        db_session.commit()

        RenameService(db_session).apply()

        db_session.refresh(mirror)
        db_session.refresh(other)
        assert mirror.kindle_delivery_status == KindleDeliveryStatus.PENDING.value
        assert mirror.kindle_delivery_attempts == 0
        assert mirror.kindle_first_pending_at is not None
        assert other.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
