# pyright: reportArgumentType=false, reportGeneralTypeIssues=false

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.errors import FailureReason, PipelineError
from backend.models import scanner as _scanner_models  # noqa: F401
from backend.models.book import RootFolder
from backend.models.scanner import Scan, ScanStatus
from backend.services.epub_service import EpubService
from backend.services.scanner.scanner_service import ScannerService, ScanResult


class BlockingScannerService(ScannerService):
    def __init__(self, *args, sleep_seconds: float = 0.0, started: threading.Event | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sleep_seconds = sleep_seconds
        self._started = started

    def scan(self, root_folder: RootFolder) -> ScanResult:
        if self._started is not None:
            self._started.set()
        if self._sleep_seconds > 0:
            time.sleep(self._sleep_seconds)
        return ScanResult(
            scan_id="stub",
            root_folder_id=int(root_folder.id),
            files_seen=0,
            files_matched=0,
            files_proposed=0,
            files_unmatched=0,
            files_failed=0,
            proposals=[],
            dismissed_skipped=0,
        )


@pytest.fixture
def shared_db_factory(tmp_path):
    db_path = tmp_path / "scanner-concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield SessionFactory
    engine.dispose()


@pytest.fixture
def root_folder(shared_db_factory, tmp_path):
    db = shared_db_factory()
    try:
        root = RootFolder(name="Library", path=str(tmp_path / "books"))
        db.add(root)
        db.commit()
        db.refresh(root)
        db.expunge(root)
        return root
    finally:
        db.close()


def test_serial_scans_succeed(shared_db_factory, root_folder):
    scanner = BlockingScannerService(
        db_session_factory=shared_db_factory,
        epub_service=EpubService(),
    )

    first = scanner.execute_scan(root_folder)
    second = scanner.execute_scan(root_folder)

    db = shared_db_factory()
    try:
        scans = db.query(Scan).order_by(Scan.id.asc()).all()
        assert first.scan_id != second.scan_id
        assert len(scans) == 2
        assert all(scan.status == ScanStatus.COMPLETED.value for scan in scans)
    finally:
        db.close()


def test_concurrent_scans_one_wins_one_409(shared_db_factory, root_folder):
    started = threading.Event()
    scanner_a = BlockingScannerService(
        db_session_factory=shared_db_factory,
        epub_service=EpubService(),
        sleep_seconds=0.4,
        started=started,
    )
    scanner_b = BlockingScannerService(
        db_session_factory=shared_db_factory,
        epub_service=EpubService(),
    )
    results: list[str] = []
    errors: list[FailureReason] = []

    def run_a() -> None:
        scanner_a.execute_scan(root_folder)
        results.append("a")

    thread = threading.Thread(target=run_a)
    thread.start()
    assert started.wait(timeout=2)

    try:
        scanner_b.execute_scan(root_folder)
    except PipelineError as exc:
        errors.append(exc.reason)

    thread.join()

    assert results == ["a"]
    assert errors == [FailureReason.PIPELINE_LOCK_HELD]


def test_five_concurrent_scans_one_wins_four_fail(shared_db_factory, root_folder):
    successes: list[str] = []
    errors: list[FailureReason] = []
    result_lock = threading.Lock()
    barrier = threading.Barrier(5)

    def run_attempt() -> None:
        scanner = BlockingScannerService(
            db_session_factory=shared_db_factory,
            epub_service=EpubService(),
            sleep_seconds=0.3,
        )
        try:
            barrier.wait()
            scanner.execute_scan(root_folder)
            with result_lock:
                successes.append("ok")
        except PipelineError as exc:
            with result_lock:
                errors.append(exc.reason)

    threads = [threading.Thread(target=run_attempt) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert len(errors) == 4
    assert all(reason == FailureReason.PIPELINE_LOCK_HELD for reason in errors)


def test_stale_running_scan_does_not_block_new_one(shared_db_factory, root_folder):
    db = shared_db_factory()
    try:
        stale_scan = Scan(
            root_folder_id=root_folder.id,
            status=ScanStatus.RUNNING.value,
            started_at=datetime.utcnow() - timedelta(hours=3),
        )
        db.add(stale_scan)
        db.commit()
        stale_id = stale_scan.id
    finally:
        db.close()

    scanner = BlockingScannerService(
        db_session_factory=shared_db_factory,
        epub_service=EpubService(),
    )
    result = scanner.execute_scan(root_folder)

    db = shared_db_factory()
    try:
        stale_scan = db.get(Scan, stale_id)
        new_scan = db.get(Scan, int(result.scan_id))
        assert stale_scan is not None
        assert stale_scan.status == ScanStatus.FAILED.value
        assert stale_scan.error_message == "abandoned (stale)"
        assert new_scan is not None
        assert new_scan.status == ScanStatus.COMPLETED.value
    finally:
        db.close()


def test_completed_scan_does_not_block_new_one(shared_db_factory, root_folder):
    db = shared_db_factory()
    try:
        db.add(
            Scan(
                root_folder_id=root_folder.id,
                status=ScanStatus.COMPLETED.value,
                started_at=datetime.utcnow() - timedelta(minutes=5),
                finished_at=datetime.utcnow() - timedelta(minutes=4),
            )
        )
        db.commit()
    finally:
        db.close()

    scanner = BlockingScannerService(
        db_session_factory=shared_db_factory,
        epub_service=EpubService(),
    )

    result = scanner.execute_scan(root_folder)

    db = shared_db_factory()
    try:
        scans = db.query(Scan).order_by(Scan.id.asc()).all()
        assert len(scans) == 2
        assert db.get(Scan, int(result.scan_id)) is not None
        assert scans[-1].status == ScanStatus.COMPLETED.value
    finally:
        db.close()
