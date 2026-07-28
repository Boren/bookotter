# pyright: reportArgumentType=false, reportGeneralTypeIssues=false

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.errors import FailureReason, PipelineError
from backend.main import app
from backend.models import blocklist, rss, scanner  # noqa: F401
from backend.models.book import Author, Book, BookStatus, RootFolder
from backend.models.scanner import DismissedScanPath, MatchProposal, MatchProposalStatus, Scan, ScanStatus
from tests.helpers import create_test_book


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def root_folder(db_session, tmp_path):
    folder = RootFolder(name="Library", path=str(tmp_path / "library"))
    db_session.add(folder)
    db_session.commit()
    db_session.refresh(folder)
    return folder


def create_scan(
    db_session,
    root_folder_id: int,
    *,
    status: str = ScanStatus.COMPLETED.value,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    files_seen: int = 0,
    files_matched: int = 0,
    files_proposed: int = 0,
    files_unmatched: int = 0,
    files_failed: int = 0,
):
    scan = Scan(
        root_folder_id=root_folder_id,
        status=status,
        started_at=started_at or datetime.utcnow(),
        finished_at=finished_at,
        files_seen=files_seen,
        files_matched=files_matched,
        files_proposed=files_proposed,
        files_unmatched=files_unmatched,
        files_failed=files_failed,
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)
    return scan


def create_proposal(
    db_session,
    scan_id: int,
    root_folder_id: int,
    *,
    relative_path: str = "book.epub",
    candidate_book_id: int | None = None,
    status: str = MatchProposalStatus.PENDING.value,
    match_method: str | None = "fuzzy",
    score: float | None = 88.0,
):
    proposal = MatchProposal(
        scan_id=scan_id,
        root_folder_id=root_folder_id,
        relative_path=relative_path,
        file_size=1234,
        candidate_book_id=candidate_book_id,
        match_method=match_method,
        score=score,
        status=status,
    )
    db_session.add(proposal)
    db_session.commit()
    db_session.refresh(proposal)
    return proposal


def test_post_scans_triggers_background_scan(client, db_session, root_folder, monkeypatch):
    def no_op_background(scan_id, background_root_folder, bind):
        return None

    monkeypatch.setattr("backend.api.routes.scanner._run_scan_in_background", no_op_background)

    response = client.post("/api/scanner/scans", json={"root_folder_id": root_folder.id})

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == ScanStatus.RUNNING.value
    scan = db_session.get(Scan, payload["scan_id"])
    assert scan is not None
    assert scan.status == ScanStatus.RUNNING.value


def test_post_scans_returns_409_when_scan_running(client, db_session, root_folder):
    create_scan(
        db_session,
        root_folder.id,
        status=ScanStatus.RUNNING.value,
        started_at=datetime.utcnow() - timedelta(minutes=10),
    )

    response = client.post("/api/scanner/scans", json={"root_folder_id": root_folder.id})

    assert response.status_code == 409
    assert response.json()["detail"] == "Scan already in progress"


def test_post_scans_returns_404_for_unknown_root_folder(client):
    response = client.post("/api/scanner/scans", json={"root_folder_id": 99999})

    assert response.status_code == 404


def test_get_current_scan_returns_running_scan(client, db_session, root_folder):
    running = create_scan(
        db_session,
        root_folder.id,
        status=ScanStatus.RUNNING.value,
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )
    create_scan(
        db_session,
        root_folder.id,
        status=ScanStatus.RUNNING.value,
        started_at=datetime.utcnow() - timedelta(hours=3),
    )

    response = client.get("/api/scanner/scans/current")

    assert response.status_code == 200
    data = response.json()
    assert data["scan"]["id"] == running.id
    assert data["scan"]["status"] == ScanStatus.RUNNING.value


def test_get_current_scan_returns_null_when_idle(client):
    response = client.get("/api/scanner/scans/current")

    assert response.status_code == 200
    assert response.json() == {"scan": None}


def test_get_scans_lists_recent_scans(client, db_session, root_folder):
    oldest = create_scan(db_session, root_folder.id, started_at=datetime.utcnow() - timedelta(days=2), files_seen=1)
    middle = create_scan(db_session, root_folder.id, started_at=datetime.utcnow() - timedelta(days=1), files_seen=2)
    newest = create_scan(db_session, root_folder.id, started_at=datetime.utcnow(), files_seen=3)

    response = client.get(f"/api/scanner/scans?root_folder_id={root_folder.id}&limit=2&offset=0")

    assert response.status_code == 200
    data = response.json()
    assert [row["id"] for row in data] == [newest.id, middle.id]
    assert oldest.id not in [row["id"] for row in data]


def test_get_proposals_filters_by_status(client, db_session, root_folder):
    scan = create_scan(db_session, root_folder.id)
    pending = create_proposal(db_session, scan.id, root_folder.id, status=MatchProposalStatus.PENDING.value)
    create_proposal(
        db_session,
        scan.id,
        root_folder.id,
        status=MatchProposalStatus.REJECTED.value,
        relative_path="rejected.epub",
    )

    response = client.get("/api/scanner/proposals?status=pending")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == pending.id


def test_get_proposals_includes_candidate_metadata(client, db_session, root_folder):
    candidate = create_test_book(db_session, title="Dune", author_name="Frank Herbert")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=candidate.id)

    response = client.get("/api/scanner/proposals")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["id"] == proposal.id
    assert data[0]["candidate_title"] == "Dune"
    assert data[0]["candidate_author"] == "Frank Herbert"
    assert data[0]["candidate_hardcover_id"] == candidate.hardcover_id


def test_post_approve_proposal_updates_book_and_proposal(client, db_session, root_folder):
    candidate = create_test_book(db_session, title="Approve Me", author_name="Author One")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(
        db_session, scan.id, root_folder.id, candidate_book_id=candidate.id, relative_path="books/a.epub"
    )

    response = client.post(f"/api/scanner/proposals/{proposal.id}/approve")

    assert response.status_code == 200
    db_session.refresh(candidate)
    db_session.refresh(proposal)
    assert candidate.file_path == "books/a.epub"
    assert candidate.root_folder_id == root_folder.id
    assert candidate.source == "scanner"
    assert proposal.status == MatchProposalStatus.APPROVED.value
    assert proposal.decided_at is not None


def test_post_approve_returns_409_when_book_already_linked(client, db_session, root_folder):
    candidate = create_test_book(
        db_session,
        title="Already Linked",
        author_name="Author One",
        file_path="existing.epub",
        root_folder_id=root_folder.id,
    )
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=candidate.id)

    response = client.post(f"/api/scanner/proposals/{proposal.id}/approve")

    assert response.status_code == 409


def test_post_approve_returns_400_for_unmatched_proposal(client, db_session, root_folder):
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=None)

    response = client.post(f"/api/scanner/proposals/{proposal.id}/approve")

    assert response.status_code == 400


def test_post_approve_returns_400_for_already_decided(client, db_session, root_folder):
    candidate = create_test_book(db_session, title="Done", author_name="Author")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(
        db_session,
        scan.id,
        root_folder.id,
        candidate_book_id=candidate.id,
        status=MatchProposalStatus.REJECTED.value,
    )

    response = client.post(f"/api/scanner/proposals/{proposal.id}/approve")

    assert response.status_code == 400


def test_post_reject_proposal(client, db_session, root_folder):
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id)

    response = client.post(f"/api/scanner/proposals/{proposal.id}/reject")

    assert response.status_code == 200
    db_session.refresh(proposal)
    assert proposal.status == MatchProposalStatus.REJECTED.value
    assert proposal.decided_at is not None


def test_post_dismiss_proposal_creates_dismissed_path(client, db_session, root_folder):
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, relative_path="ignored/book.epub")

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/dismiss",
        json={"proposal_id": proposal.id, "add_to_dismissed_paths": True},
    )

    assert response.status_code == 200
    db_session.refresh(proposal)
    dismissed = db_session.query(DismissedScanPath).filter(DismissedScanPath.relative_path == "ignored/book.epub").one()
    assert proposal.status == MatchProposalStatus.REJECTED.value
    assert dismissed.root_folder_id == root_folder.id


def test_post_dismiss_is_idempotent(client, db_session, root_folder):
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, relative_path="ignored/once.epub")

    first = client.post(
        f"/api/scanner/proposals/{proposal.id}/dismiss",
        json={"proposal_id": proposal.id, "add_to_dismissed_paths": True},
    )
    second = client.post(
        f"/api/scanner/proposals/{proposal.id}/dismiss",
        json={"proposal_id": proposal.id, "add_to_dismissed_paths": True},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    rows = db_session.query(DismissedScanPath).filter(DismissedScanPath.relative_path == "ignored/once.epub").all()
    assert len(rows) == 1


def test_delete_dismissed_path_removes_row(client, db_session, root_folder):
    dismissed = DismissedScanPath(root_folder_id=root_folder.id, relative_path="gone.epub")
    db_session.add(dismissed)
    db_session.commit()
    db_session.refresh(dismissed)

    response = client.delete(f"/api/scanner/dismissed-paths/{dismissed.id}")

    assert response.status_code == 204
    assert db_session.get(DismissedScanPath, dismissed.id) is None


def test_post_hardcover_search_returns_results(client, monkeypatch):
    mock_client = MagicMock()
    mock_client.search_books.return_value = [
        {
            "id": 42,
            "title": "The Hobbit",
            "author_names": ["J.R.R. Tolkien"],
            "isbns": ["9780261103344"],
        }
    ]
    monkeypatch.setattr("backend.api.routes.scanner._get_hardcover_client", lambda: mock_client)

    response = client.post("/api/scanner/hardcover/search", json={"query": "hobbit", "limit": 5})

    assert response.status_code == 200
    assert response.json() == [
        {
            "hardcover_id": 42,
            "title": "The Hobbit",
            "author_names": ["J.R.R. Tolkien"],
            "isbns": ["9780261103344"],
        }
    ]


def test_post_hardcover_search_returns_503_on_auth_failure(client, monkeypatch):
    mock_client = MagicMock()
    mock_client.search_books.side_effect = PipelineError(
        "bad token",
        FailureReason.HARDCOVER_AUTH_FAILED,
    )
    monkeypatch.setattr("backend.api.routes.scanner._get_hardcover_client", lambda: mock_client)

    response = client.post("/api/scanner/hardcover/search", json={"query": "hobbit", "limit": 5})

    assert response.status_code == 503


def test_post_link_hardcover_creates_new_book_and_approves_proposal(client, db_session, root_folder, monkeypatch):
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(
        db_session,
        scan.id,
        root_folder.id,
        candidate_book_id=None,
        relative_path="bootstrap.epub",
        match_method=None,
        score=None,
    )
    mock_client = MagicMock()
    mock_client.get_book_by_id.return_value = {
        "id": 777,
        "title": "Bootstrap Book",
        "author_names": ["Bootstrap Author"],
        "isbns": ["9780000000001"],
    }
    monkeypatch.setattr("backend.api.routes.scanner._get_hardcover_client", lambda: mock_client)

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/link-hardcover",
        json={"proposal_id": proposal.id, "hardcover_id": 777},
    )

    assert response.status_code == 200
    payload = response.json()
    created_book = db_session.get(Book, payload["book_id"])
    db_session.refresh(proposal)
    assert created_book is not None
    assert created_book.title == "Bootstrap Book"
    assert created_book.hardcover_id == "777"
    assert created_book.file_path == "bootstrap.epub"
    assert created_book.root_folder_id == root_folder.id
    assert created_book.status == BookStatus.IN_LIBRARY.value
    assert proposal.status == MatchProposalStatus.APPROVED.value
    assert proposal.candidate_book_id == created_book.id
    assert proposal.match_method == "hardcover_bootstrap"
    assert payload["proposal"]["candidate_title"] == "Bootstrap Book"


def test_post_link_hardcover_returns_409_for_duplicate_hardcover_id(client, db_session, root_folder):
    existing_author = Author(name="Author")
    db_session.add(existing_author)
    db_session.flush()
    existing_book = Book(
        title="Existing",
        author_id=existing_author.id,
        hardcover_id="777",
        status=BookStatus.WANTED.value,
    )
    db_session.add(existing_book)
    db_session.commit()
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=None)

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/link-hardcover",
        json={"proposal_id": proposal.id, "hardcover_id": 777},
    )

    assert response.status_code == 409


def test_post_approve_marks_book_in_library(client, db_session, root_folder):
    candidate = create_test_book(db_session, title="Approve Me", author_name="Author A")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=candidate.id)

    response = client.post(f"/api/scanner/proposals/{proposal.id}/approve")

    assert response.status_code == 200
    db_session.refresh(candidate)
    assert candidate.status == BookStatus.IN_LIBRARY.value
    assert candidate.file_path == proposal.relative_path
    assert candidate.file_size == proposal.file_size
    assert candidate.root_folder_id == root_folder.id
    assert candidate.source == "scanner"


def test_post_bulk_approve_mixes_success_and_skips(client, db_session, root_folder):
    linked = create_test_book(db_session, title="Already Linked", author_name="Author L", file_path="linked.epub")
    fresh = create_test_book(db_session, title="Fresh", author_name="Author F")
    scan = create_scan(db_session, root_folder.id)
    good = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=fresh.id, relative_path="fresh.epub")
    conflicting = create_proposal(
        db_session, scan.id, root_folder.id, candidate_book_id=linked.id, relative_path="dupe.epub"
    )
    unmatched = create_proposal(
        db_session, scan.id, root_folder.id, candidate_book_id=None, relative_path="nomatch.epub"
    )

    response = client.post(
        "/api/scanner/proposals/bulk-approve",
        json={"proposal_ids": [good.id, conflicting.id, unmatched.id, 99999]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["approved"] == 1
    skipped_reasons = {entry["proposal_id"]: entry["reason"] for entry in payload["skipped"]}
    assert skipped_reasons == {
        conflicting.id: "book already linked to a file",
        unmatched.id: "no candidate book",
        99999: "not found",
    }
    db_session.refresh(fresh)
    db_session.refresh(good)
    assert fresh.status == BookStatus.IN_LIBRARY.value
    assert fresh.file_path == "fresh.epub"
    assert good.status == MatchProposalStatus.APPROVED.value


def test_post_link_book_links_existing_book(client, db_session, root_folder):
    book = create_test_book(db_session, title="Manual Target", author_name="Author M")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(
        db_session,
        scan.id,
        root_folder.id,
        candidate_book_id=None,
        relative_path="manual.epub",
        match_method=None,
        score=None,
    )

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/link-book",
        json={"proposal_id": proposal.id, "book_id": book.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == MatchProposalStatus.APPROVED.value
    assert payload["match_method"] == "manual"
    assert payload["candidate_book_id"] == book.id
    db_session.refresh(book)
    assert book.status == BookStatus.IN_LIBRARY.value
    assert book.file_path == "manual.epub"


def test_post_link_book_returns_409_for_already_linked_book(client, db_session, root_folder):
    book = create_test_book(db_session, title="Taken", author_name="Author T", file_path="taken.epub")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=None)

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/link-book",
        json={"proposal_id": proposal.id, "book_id": book.id},
    )

    assert response.status_code == 409


def test_post_link_hardcover_returns_400_for_already_linked_proposal(client, db_session, root_folder):
    candidate = create_test_book(db_session, title="Candidate", author_name="Author")
    scan = create_scan(db_session, root_folder.id)
    proposal = create_proposal(db_session, scan.id, root_folder.id, candidate_book_id=candidate.id)

    response = client.post(
        f"/api/scanner/proposals/{proposal.id}/link-hardcover",
        json={"proposal_id": proposal.id, "hardcover_id": 777},
    )

    assert response.status_code == 400
