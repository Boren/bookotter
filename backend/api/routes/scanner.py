# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportPossiblyUnboundVariable=false

"""Scanner API routes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.clients.hardcover_client import HardcoverClient
from backend.config import load_config
from backend.database import get_db
from backend.errors import FailureReason, PipelineError
from backend.models.book import Author, Book, BookStatus, RootFolder
from backend.models.scanner import DismissedScanPath, MatchProposal, MatchProposalStatus, Scan, ScanStatus
from backend.services.epub_service import EpubService
from backend.services.scanner.scanner_service import ScannerService
from backend.services.websocket_manager import manager as ws_manager

router = APIRouter(prefix="/api/scanner", tags=["scanner"])

STALE_SCAN_WINDOW = timedelta(hours=2)


class ScanRequest(BaseModel):
    root_folder_id: int


class ScanSummary(BaseModel):
    id: int
    root_folder_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    files_seen: int
    files_matched: int
    files_proposed: int
    files_unmatched: int
    files_failed: int
    error_message: str | None


class CurrentScanResponse(BaseModel):
    scan: ScanSummary | None


class MatchProposalResponse(BaseModel):
    id: int
    scan_id: int
    root_folder_id: int
    relative_path: str
    file_size: int
    candidate_book_id: int | None
    match_method: str | None
    score: float | None
    status: str
    created_at: datetime
    decided_at: datetime | None
    candidate_title: str | None
    candidate_author: str | None
    candidate_hardcover_id: str | None


class HardcoverSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class HardcoverSearchResultItem(BaseModel):
    hardcover_id: int
    title: str
    author_names: list[str]
    isbns: list[str]


class LinkUnmatchedRequest(BaseModel):
    proposal_id: int
    hardcover_id: int


class DismissProposalRequest(BaseModel):
    proposal_id: int
    add_to_dismissed_paths: bool = False


class DismissedScanPathResponse(BaseModel):
    id: int
    root_folder_id: int
    relative_path: str
    dismissed_at: datetime


def _make_scanner_service(db: Session) -> ScannerService:
    bind = db.get_bind()
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind)
    return ScannerService(
        db_session_factory=session_factory,
        epub_service=EpubService(),
        ws_manager=ws_manager,
    )


def _run_scan_in_background(scan_id: int, root_folder: RootFolder, bind) -> None:
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind)
    service = ScannerService(
        db_session_factory=session_factory,
        epub_service=EpubService(),
        ws_manager=ws_manager,
    )
    started_at = datetime.utcnow()
    original_callback = service._progress_callback

    def progress_handler(progress) -> None:
        event = {
            "scan_id": scan_id,
            "root_folder_id": progress.root_folder_id,
            "files_seen": progress.files_seen,
            "files_matched": progress.files_matched,
            "files_proposed": progress.files_proposed,
            "files_unmatched": progress.files_unmatched,
            "files_failed": progress.files_failed,
            "current_path": progress.current_path,
            "finished": progress.finished,
        }
        service._broadcast("scan_progress", event)
        if original_callback is not None:
            original_callback(progress)

    service._supersede_pending_proposals(int(root_folder.id))
    service._broadcast(
        "scan_started",
        {
            "scan_id": scan_id,
            "root_folder_id": int(root_folder.id),
            "root_folder_path": str(root_folder.path),
            "started_at": started_at.isoformat(),
        },
    )

    try:
        service._progress_callback = progress_handler
        raw_result = service.scan(root_folder)
        result = service._persist_scan_result(scan_id, root_folder, raw_result)
    except Exception as exc:
        service._progress_callback = original_callback
        service._mark_scan_failed(scan_id, exc)
        service._broadcast(
            "scan_failed",
            {
                "scan_id": scan_id,
                "root_folder_id": int(root_folder.id),
                "error_message": str(exc),
            },
        )
        raise
    finally:
        service._progress_callback = original_callback

    duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
    service._broadcast(
        "scan_completed",
        {
            "scan_id": scan_id,
            "root_folder_id": int(root_folder.id),
            "files_seen": result.files_seen,
            "files_matched": result.files_matched,
            "files_proposed": result.files_proposed,
            "files_unmatched": result.files_unmatched,
            "files_failed": result.files_failed,
            "duration_ms": duration_ms,
        },
    )


def _scan_to_summary(scan: Scan) -> ScanSummary:
    return ScanSummary(
        id=int(scan.id),
        root_folder_id=int(scan.root_folder_id),
        status=str(scan.status),
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        files_seen=int(scan.files_seen),
        files_matched=int(scan.files_matched),
        files_proposed=int(scan.files_proposed),
        files_unmatched=int(scan.files_unmatched),
        files_failed=int(scan.files_failed),
        error_message=scan.error_message,
    )


def _proposal_query(db: Session):
    return (
        db.query(MatchProposal, Book, Author)
        .outerjoin(Book, MatchProposal.candidate_book_id == Book.id)
        .outerjoin(Author, Book.author_id == Author.id)
    )


def _proposal_to_response(
    proposal: MatchProposal, book: Book | None = None, author: Author | None = None
) -> MatchProposalResponse:
    return MatchProposalResponse(
        id=int(proposal.id),
        scan_id=int(proposal.scan_id),
        root_folder_id=int(proposal.root_folder_id),
        relative_path=str(proposal.relative_path),
        file_size=int(proposal.file_size),
        candidate_book_id=int(proposal.candidate_book_id) if proposal.candidate_book_id is not None else None,
        match_method=proposal.match_method,
        score=float(proposal.score) if proposal.score is not None else None,
        status=str(proposal.status),
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        candidate_title=book.title if book is not None else None,
        candidate_author=author.name if author is not None else None,
        candidate_hardcover_id=book.hardcover_id if book is not None else None,
    )


def _get_proposal_response(db: Session, proposal_id: int) -> MatchProposalResponse:
    row = _proposal_query(db).filter(MatchProposal.id == proposal_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    proposal, book, author = row
    return _proposal_to_response(proposal, book, author)


def _get_pending_proposal(db: Session, proposal_id: int) -> MatchProposal:
    proposal = db.get(MatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    if proposal.status != MatchProposalStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Proposal has already been decided")
    return proposal


def _resolve_author(db: Session, author_name: str | None) -> Author:
    normalized_name = (author_name or "Unknown Author").strip() or "Unknown Author"
    author = db.query(Author).filter(Author.name == normalized_name).first()
    if author is None:
        author = Author(name=normalized_name)
        db.add(author)
        db.flush()
    return author


def _get_hardcover_client() -> HardcoverClient:
    config = load_config()
    hc_config = config.get("hardcover", {})
    return HardcoverClient(
        api_token=hc_config.get("api_token", ""),
        api_url=hc_config.get("api_url", "https://api.hardcover.app/v1/graphql"),
    )


def _translate_hardcover_error(exc: Exception) -> None:
    if isinstance(exc, PipelineError) and exc.reason in {
        FailureReason.HARDCOVER_AUTH_FAILED,
        FailureReason.HARDCOVER_RATE_LIMITED,
        FailureReason.HARDCOVER_UNREACHABLE,
    }:
        raise HTTPException(status_code=503, detail="Hardcover service unavailable") from exc
    raise exc


def _lookup_hardcover_book(hardcover_id: int) -> dict:
    client = _get_hardcover_client()
    try:
        results = client.search_books(str(hardcover_id), limit=20)
    except Exception as exc:
        _translate_hardcover_error(exc)

    for result in results:
        if result.get("id") == hardcover_id:
            return result
    raise HTTPException(status_code=404, detail=f"Hardcover book {hardcover_id} not found")


def _ensure_proposal_id_matches(path_proposal_id: int, body_proposal_id: int) -> None:
    if path_proposal_id != body_proposal_id:
        raise HTTPException(status_code=400, detail="Proposal ID mismatch between path and body")


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
def trigger_scan(body: ScanRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    root_folder = db.get(RootFolder, body.root_folder_id)
    if root_folder is None:
        raise HTTPException(status_code=404, detail=f"Root folder {body.root_folder_id} not found")

    stale_before = datetime.utcnow() - STALE_SCAN_WINDOW
    active_scan = (
        db.query(Scan)
        .filter(Scan.root_folder_id == body.root_folder_id, Scan.status == ScanStatus.RUNNING.value)
        .filter(Scan.started_at >= stale_before)
        .order_by(Scan.started_at.desc())
        .first()
    )
    if active_scan is not None:
        raise HTTPException(status_code=409, detail="Scan already in progress")

    bind = db.get_bind()
    db.expunge(root_folder)
    service = _make_scanner_service(db)
    try:
        scan_row = service._acquire_scan_lock(root_folder, holder="user")
    except PipelineError as exc:
        if exc.reason == FailureReason.PIPELINE_LOCK_HELD:
            raise HTTPException(status_code=409, detail="Scan already in progress") from exc
        raise

    background_tasks.add_task(_run_scan_in_background, scan_row.id, root_folder, bind)
    return {"scan_id": scan_row.id, "status": ScanStatus.RUNNING.value}


@router.get("/scans/current", response_model=CurrentScanResponse)
def get_current_scan(db: Session = Depends(get_db)):
    stale_before = datetime.utcnow() - STALE_SCAN_WINDOW
    scan = (
        db.query(Scan)
        .filter(Scan.status == ScanStatus.RUNNING.value)
        .filter(Scan.started_at >= stale_before)
        .order_by(Scan.started_at.desc())
        .first()
    )
    return CurrentScanResponse(scan=_scan_to_summary(scan) if scan is not None else None)


@router.get("/scans", response_model=list[ScanSummary])
def list_scans(
    root_folder_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Scan)
    if root_folder_id is not None:
        query = query.filter(Scan.root_folder_id == root_folder_id)
    scans = query.order_by(Scan.started_at.desc()).offset(offset).limit(limit).all()
    return [_scan_to_summary(scan) for scan in scans]


@router.get("/proposals", response_model=list[MatchProposalResponse])
def list_proposals(
    root_folder_id: int | None = Query(default=None),
    scan_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = _proposal_query(db)
    if root_folder_id is not None:
        query = query.filter(MatchProposal.root_folder_id == root_folder_id)
    if scan_id is not None:
        query = query.filter(MatchProposal.scan_id == scan_id)
    if status is not None:
        query = query.filter(MatchProposal.status == status)

    rows = query.order_by(MatchProposal.created_at.desc()).offset(offset).limit(limit).all()
    return [_proposal_to_response(proposal, book, author) for proposal, book, author in rows]


@router.post("/proposals/{proposal_id}/approve", response_model=MatchProposalResponse)
def approve_proposal(proposal_id: int, db: Session = Depends(get_db)):
    proposal = _get_pending_proposal(db, proposal_id)
    if proposal.candidate_book_id is None:
        raise HTTPException(status_code=400, detail="Cannot approve unmatched proposal")

    book = db.get(Book, proposal.candidate_book_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book {proposal.candidate_book_id} not found")
    if book.file_path:
        raise HTTPException(status_code=409, detail="Candidate book is already linked to a file")

    now = datetime.utcnow()
    book.file_path = proposal.relative_path
    book.source = "scanner"
    book.root_folder_id = proposal.root_folder_id
    proposal.status = MatchProposalStatus.APPROVED.value
    proposal.decided_at = now

    db.commit()
    return _get_proposal_response(db, proposal_id)


@router.post("/proposals/{proposal_id}/reject", response_model=MatchProposalResponse)
def reject_proposal(proposal_id: int, db: Session = Depends(get_db)):
    proposal = _get_pending_proposal(db, proposal_id)
    proposal.status = MatchProposalStatus.REJECTED.value
    proposal.decided_at = datetime.utcnow()
    db.commit()
    return _get_proposal_response(db, proposal_id)


@router.post("/proposals/{proposal_id}/dismiss", response_model=MatchProposalResponse)
def dismiss_proposal(proposal_id: int, body: DismissProposalRequest, db: Session = Depends(get_db)):
    _ensure_proposal_id_matches(proposal_id, body.proposal_id)

    proposal = db.get(MatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")

    if proposal.status == MatchProposalStatus.PENDING.value:
        proposal.status = MatchProposalStatus.REJECTED.value
        proposal.decided_at = datetime.utcnow()
    elif proposal.status != MatchProposalStatus.REJECTED.value:
        raise HTTPException(status_code=400, detail="Proposal has already been decided")

    dismissed = DismissedScanPath(
        root_folder_id=proposal.root_folder_id,
        relative_path=proposal.relative_path,
    )
    db.add(dismissed)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        proposal = db.get(MatchProposal, proposal_id)
        if proposal is not None and proposal.status == MatchProposalStatus.PENDING.value:
            proposal.status = MatchProposalStatus.REJECTED.value
            proposal.decided_at = datetime.utcnow()
            db.commit()
    return _get_proposal_response(db, proposal_id)


@router.delete("/dismissed-paths/{dismissed_path_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dismissed_path(dismissed_path_id: int, db: Session = Depends(get_db)) -> Response:
    dismissed_path = db.get(DismissedScanPath, dismissed_path_id)
    if dismissed_path is None:
        raise HTTPException(status_code=404, detail=f"Dismissed path {dismissed_path_id} not found")
    db.delete(dismissed_path)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dismissed-paths", response_model=list[DismissedScanPathResponse])
def list_dismissed_paths(root_folder_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    query = db.query(DismissedScanPath)
    if root_folder_id is not None:
        query = query.filter(DismissedScanPath.root_folder_id == root_folder_id)
    rows = query.order_by(DismissedScanPath.dismissed_at.desc()).all()
    return [
        DismissedScanPathResponse(
            id=int(row.id),
            root_folder_id=int(row.root_folder_id),
            relative_path=str(row.relative_path),
            dismissed_at=row.dismissed_at,
        )
        for row in rows
    ]


@router.post("/hardcover/search", response_model=list[HardcoverSearchResultItem])
def search_hardcover(body: HardcoverSearchRequest):
    client = _get_hardcover_client()
    try:
        results = client.search_books(body.query, limit=body.limit)
    except Exception as exc:
        _translate_hardcover_error(exc)

    return [
        HardcoverSearchResultItem(
            hardcover_id=int(result["id"]),
            title=str(result["title"]),
            author_names=[str(name) for name in result.get("author_names", [])],
            isbns=[str(isbn) for isbn in result.get("isbns", [])],
        )
        for result in results
    ]


@router.post("/proposals/{proposal_id}/link-hardcover")
def link_hardcover(proposal_id: int, body: LinkUnmatchedRequest, db: Session = Depends(get_db)):
    _ensure_proposal_id_matches(proposal_id, body.proposal_id)

    proposal = _get_pending_proposal(db, proposal_id)
    if proposal.candidate_book_id is not None:
        raise HTTPException(status_code=400, detail="Proposal already has a candidate book; use approve instead")

    existing = db.query(Book).filter(Book.hardcover_id == str(body.hardcover_id)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A book with this Hardcover ID already exists")

    hardcover_book = _lookup_hardcover_book(body.hardcover_id)
    author = _resolve_author(db, (hardcover_book.get("author_names") or [None])[0])
    isbns = [str(isbn) for isbn in hardcover_book.get("isbns", []) if isbn]

    book = Book(
        title=str(hardcover_book.get("title") or "Untitled"),
        author_id=author.id,
        hardcover_id=str(body.hardcover_id),
        isbn=isbns[0] if isbns else None,
        source="scanner",
        root_folder_id=proposal.root_folder_id,
        file_path=proposal.relative_path,
        status=BookStatus.IN_LIBRARY.value,
    )
    db.add(book)
    db.flush()

    proposal.status = MatchProposalStatus.APPROVED.value
    proposal.decided_at = datetime.utcnow()
    proposal.candidate_book_id = book.id
    proposal.match_method = "hardcover_bootstrap"
    proposal.score = None

    db.commit()
    db.refresh(book)

    return {
        "book_id": book.id,
        "proposal": _get_proposal_response(db, proposal_id).model_dump(),
    }
