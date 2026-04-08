"""
Search and grab API routes.
Handles manual book search via Prowlarr and grabbing results for download.
"""

import hashlib
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.clients.prowlarr_client import ProwlarrClient
from backend.clients.qbittorrent_client import QBittorrentClient
from backend.config import load_config
from backend.database import get_db
from backend.models.book import Book, BookStatus, Download, DownloadStatus
from backend.services.pipeline_states import transition_book
from backend.services.search_service import SearchService

logger = logging.getLogger(__name__)

router = APIRouter()


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
):
    """
    Search for books via Prowlarr.

    Returns a ranked list of EPUB results filtered and sorted by quality.
    """
    try:
        prowlarr = _get_prowlarr_client()
        search_service = SearchService(prowlarr_client=prowlarr)
        results = search_service.search_book(title=query, author=author)
        return {"results": results, "total": len(results)}

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

    torrent_hash = result.guid or hashlib.sha1(download_url.encode()).hexdigest()

    existing = db.query(Download).filter(Download.torrent_hash == torrent_hash).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Download already exists (id={existing.id})")

    try:
        qbt = _get_qbittorrent_client()
        config = load_config()
        category = config.get("qbittorrent", {}).get("category", "books")

        qbt.ensure_category_exists(category)
        success = qbt.add_torrent(torrent_url=download_url, category=category)
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

    transition_book(book, BookStatus.GRABBED.value)
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

    transition_book(book, BookStatus.SEARCHING.value)
    book.search_attempts = (book.search_attempts or 0) + 1
    book.last_searched_at = datetime.utcnow()
    db.commit()

    try:
        prowlarr = _get_prowlarr_client()
        search_service = SearchService(prowlarr_client=prowlarr)
        results = search_service.search_book(title=book.title, author=author_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto-search failed for book {book_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

    if not results:
        transition_book(book, BookStatus.WANTED.value)
        db.commit()
        return {"success": False, "message": "No results found", "book_id": book_id, "results_count": 0}

    best = results[0]
    download_url = best.get("magnet_url") or best.get("download_url")
    if not download_url:
        transition_book(book, BookStatus.WANTED.value)
        db.commit()
        return {"success": False, "message": "Best result has no download URL", "book_id": book_id}

    torrent_hash = best.get("guid") or hashlib.sha1(download_url.encode()).hexdigest()

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
        category = config.get("qbittorrent", {}).get("category", "books")
        qbt.ensure_category_exists(category)

        success = qbt.add_torrent(torrent_url=download_url, category=category)
        if not success:
            transition_book(book, BookStatus.WANTED.value)
            db.commit()
            return {"success": False, "message": "Failed to add torrent to qBittorrent", "book_id": book_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add torrent for book {book_id}: {e}")
        transition_book(book, BookStatus.WANTED.value)
        db.commit()
        raise HTTPException(status_code=502, detail=f"qBittorrent error: {e}")

    download = Download(
        book_id=book.id,
        torrent_hash=torrent_hash,
        torrent_name=best.get("title") or "Unknown",
        indexer_name=best.get("indexer") or "Unknown",
        download_url=download_url,
        size=best.get("size") or 0,
        seeders=best.get("seeders") or 0,
        status=DownloadStatus.QUEUED.value,
    )
    db.add(download)

    transition_book(book, BookStatus.GRABBED.value)
    book.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(download)

    logger.info(f"Auto-grabbed '{best.get('title')}' for book '{book.title}' (download_id={download.id})")

    return {
        "success": True,
        "download_id": download.id,
        "book_id": book_id,
        "torrent_hash": torrent_hash,
        "result_title": best.get("title"),
        "results_count": len(results),
    }
