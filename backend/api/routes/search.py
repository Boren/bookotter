# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
"""
Search and grab API routes.
Handles manual book search via Prowlarr and grabbing results for download.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.clients.prowlarr_client import ProwlarrClient
from backend.clients.qbittorrent_client import QBittorrentClient
from backend.config import get_qbit_category, load_config
from backend.database import get_db
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_states import transition_book
from backend.services.search_service import SearchService
from backend.services.torrent_hash import (
    extract_info_hash_from_url,
    fetch_and_hash_torrent,
    spooled_torrent_path,
)


def _add_torrent_to_qbit(qbt, torrent_hash: str, download_url: str, category: str) -> bool:
    """Add a torrent to qBittorrent, preferring the spooled .torrent file bytes."""
    added = False
    spooled = spooled_torrent_path(torrent_hash)
    if spooled is not None:
        try:
            added = qbt.add_torrent_file(spooled.read_bytes(), category=category)
        except OSError as exc:
            logger.warning("Could not read spooled torrent %s: %s", torrent_hash, exc)
    else:
        added = qbt.add_torrent(torrent_url=download_url, category=category)

    if not added and qbt.get_torrent_properties(torrent_hash) is not None:
        logger.info("Torrent %s already present in qBittorrent — treating add as success", torrent_hash)
        return True
    return added


logger = logging.getLogger(__name__)

router = APIRouter()


def _require_transition(book: Book, target_status: str, db: Session, detail: str) -> None:
    if transition_book(book, target_status, db):
        return

    db.rollback()
    raise HTTPException(status_code=409, detail=detail)


class SearchResultItem(BaseModel):
    """A single search result from Prowlarr."""

    guid: str | None = None
    indexer_id: int | None = None
    indexer: str | None = None
    title: str | None = None
    size: int | None = None
    seeders: int | None = None
    leechers: int | None = None
    download_url: str | None = None
    magnet_url: str | None = None
    categories: list[dict] | None = None
    protocol: str | None = None
    publish_date: str | None = None
    age_days: float = 0.0
    rejections: list[str] = []
    approved: bool = True


class GrabRequest(BaseModel):
    """Request body for grabbing a search result."""

    book_id: int
    result: SearchResultItem


def _get_prowlarr_client() -> ProwlarrClient:
    """Create a ProwlarrClient from config."""
    config = load_config()
    prowlarr_config = config.get("prowlarr", {})
    api_key = prowlarr_config.get("api_key")
    base_url = prowlarr_config.get("base_url", "http://localhost:9696")

    if not api_key:
        raise HTTPException(status_code=503, detail="Prowlarr API key not configured")

    return ProwlarrClient(api_key=api_key, base_url=base_url)


def _get_qbittorrent_client() -> QBittorrentClient:
    """Create a QBittorrentClient from config."""
    config = load_config()
    qbt_config = config.get("qbittorrent", {})
    username = qbt_config.get("username")
    password = qbt_config.get("password")
    base_url = qbt_config.get("base_url", "http://localhost:8080")

    if not username or not password:
        raise HTTPException(status_code=503, detail="qBittorrent credentials not configured")

    return QBittorrentClient(username=username, password=password, base_url=base_url)


@router.get("")
async def search_books(
    query: str = Query(..., min_length=1, description="Book title to search for"),
    author: str = Query(default="", description="Author name (optional)"),
    db: Session = Depends(get_db),
):
    """
    Search for books via Prowlarr.

    Returns a ranked list of EPUB results filtered and sorted by quality.
    """
    try:
        prowlarr = _get_prowlarr_client()
        search_service = SearchService(prowlarr_client=prowlarr, db=db)
        results = search_service.search_book(title=query, author=author)
        return {"results": [result.to_dict() for result in results], "total": len(results)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed for query='{query}' author='{author}': {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")


@router.post("/grab")
async def grab_result(body: GrabRequest, db: Session = Depends(get_db)):
    """
    Grab a search result for a book.

    Creates a Download record and adds the torrent to qBittorrent.
    Updates the book status through the pipeline state machine.
    """
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == body.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {body.book_id} not found")

    result = body.result
    download_url = result.magnet_url or result.download_url
    if not download_url:
        raise HTTPException(status_code=422, detail="Result has no download_url or magnet_url")

    torrent_hash = (
        extract_info_hash_from_url(result.magnet_url)
        or extract_info_hash_from_url(download_url)
        or fetch_and_hash_torrent(result.download_url)
    )
    if not torrent_hash:
        raise HTTPException(
            status_code=422,
            detail="Selected result has no usable magnet/info-hash — cannot grab",
        )

    existing = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Download already exists (id={existing.id})")

    try:
        qbt = _get_qbittorrent_client()
        config = load_config()
        category = get_qbit_category(config)

        qbt.ensure_category_exists(category)
        success = _add_torrent_to_qbit(qbt, torrent_hash, download_url, category)
        if not success:
            raise HTTPException(status_code=502, detail="Failed to add torrent to qBittorrent")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add torrent to qBittorrent: {e}")
        raise HTTPException(status_code=502, detail=f"qBittorrent error: {e}")

    download = Download(
        book_id=book.id,
        torrent_hash=torrent_hash,
        torrent_name=result.title or "Unknown",
        indexer_name=result.indexer or "Unknown",
        download_url=download_url,
        size=result.size or 0,
        seeders=result.seeders or 0,
        status=DownloadStatus.QUEUED.value,
    )
    db.add(download)

    _require_transition(book, BookStatus.GRABBED.value, db, f"Book {book.id} could not transition to grabbed")
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(download)

    logger.info(f"Grabbed '{result.title}' for book '{book.title}' (download_id={download.id})")

    return {
        "success": True,
        "download_id": download.id,
        "book_id": book.id,
        "torrent_hash": torrent_hash,
        "status": download.status,
    }


@router.post("/auto/{book_id}")
async def auto_search_and_grab(book_id: int, db: Session = Depends(get_db)):
    """
    Auto-search Prowlarr and grab the best result for a book.

    Searches by title + author, picks the top-ranked result, and grabs it.
    Used by the pipeline and manual trigger button.
    """
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    author_name = book.author.name if book.author else ""

    _require_transition(book, BookStatus.SEARCHING.value, db, f"Book {book.id} could not transition to searching")
    book.search_attempts = (book.search_attempts or 0) + 1
    book.last_searched_at = datetime.utcnow()
    db.commit()

    try:
        prowlarr = _get_prowlarr_client()
        search_service = SearchService(prowlarr_client=prowlarr, db=db)
        results = search_service.search_book(title=book.title, author=author_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto-search failed for book {book_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

    if not results:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        return {"success": False, "message": "No results found", "book_id": book_id, "results_count": 0}

    approved_results = [result for result in results if result.approved]
    if not approved_results:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        return {
            "success": False,
            "message": "No approved results found",
            "book_id": book_id,
            "results_count": len(results),
        }

    best = approved_results[0]
    download_url = best.magnet_url or best.download_url
    if not download_url:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        return {"success": False, "message": "Best result has no download URL", "book_id": book_id}

    torrent_hash = (
        extract_info_hash_from_url(best.magnet_url)
        or extract_info_hash_from_url(download_url)
        or fetch_and_hash_torrent(best.download_url)
    )
    if not torrent_hash:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        return {
            "success": False,
            "message": "No usable magnet/info-hash in best result — cannot grab",
            "book_id": book_id,
        }

    existing = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
    if existing:
        return {
            "success": False,
            "message": f"Download already exists (id={existing.id})",
            "book_id": book_id,
            "download_id": existing.id,
        }

    try:
        qbt = _get_qbittorrent_client()
        config = load_config()
        category = get_qbit_category(config)
        qbt.ensure_category_exists(category)

        success = _add_torrent_to_qbit(qbt, torrent_hash, download_url, category)
        if not success:
            _require_transition(
                book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted"
            )
            db.commit()
            return {"success": False, "message": "Failed to add torrent to qBittorrent", "book_id": book_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add torrent for book {book_id}: {e}")
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        raise HTTPException(status_code=502, detail=f"qBittorrent error: {e}")

    download = Download(
        book_id=book.id,
        torrent_hash=torrent_hash,
        torrent_name=best.title or "Unknown",
        indexer_name=best.indexer or "Unknown",
        download_url=download_url,
        size=best.size or 0,
        seeders=best.seeders or 0,
        status=DownloadStatus.QUEUED.value,
    )
    db.add(download)

    _require_transition(book, BookStatus.GRABBED.value, db, f"Book {book.id} could not transition to grabbed")
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(download)

    logger.info(f"Auto-grabbed '{best.title}' for book '{book.title}' (download_id={download.id})")

    return {
        "success": True,
        "download_id": download.id,
        "book_id": book_id,
        "torrent_hash": torrent_hash,
        "result_title": best.title,
        "results_count": len(results),
    }


@router.post("/preview/{book_id}")
async def search_preview(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    _require_transition(book, BookStatus.SEARCHING.value, db, f"Book {book.id} could not transition to searching")
    book.search_attempts = (book.search_attempts or 0) + 1
    book.last_searched_at = datetime.utcnow()
    db.commit()

    try:
        prowlarr = _get_prowlarr_client()
        search_service = SearchService(prowlarr_client=prowlarr, db=db)
        author_name = book.author.name if book.author else ""
        results = search_service.search_book(title=book.title, author=author_name)

    except HTTPException:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        raise
    except Exception as e:
        logger.error(f"Preview search failed for book {book_id}: {e}")
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

    if not results:
        _require_transition(book, BookStatus.WANTED.value, db, f"Book {book.id} could not transition back to wanted")
        db.commit()

    return {
        "book_id": book.id,
        "book_title": book.title,
        "book_author": book.author.name if book.author else None,
        "results": [result.to_dict() for result in results],
        "total": len(results),
    }
