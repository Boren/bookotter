"""
Download queue API routes.
Handles listing active downloads and cancelling them.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from backend.clients.qbittorrent_client import QBittorrentClient
from backend.config import load_config
from backend.database import get_db
from backend.models.book import Book, BookStatus, Download, DownloadStatus

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_qbit_client() -> QBittorrentClient | None:
    """Create a qBittorrent client from config. Returns None if not configured."""
    config = load_config()
    qbit_config = config.get("qbittorrent", {})

    username = qbit_config.get("username")
    password = qbit_config.get("password")
    base_url = qbit_config.get("base_url", "http://localhost:8080")

    if not username or not password:
        return None

    return QBittorrentClient(username=username, password=password, base_url=base_url)


def _enrich_with_qbit_data(downloads: list[Download], qbit_client: QBittorrentClient | None) -> dict[str, dict]:
    """Fetch live progress/speed from qBittorrent for active downloads."""
    if not qbit_client or not downloads:
        return {}

    active_hashes = [
        d.torrent_hash for d in downloads if d.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)
    ]
    if not active_hashes:
        return {}

    try:
        torrents = qbit_client.get_torrents(hashes=active_hashes)
        return {t["hash"]: t for t in torrents}
    except Exception:
        logger.warning("Failed to fetch live torrent data from qBittorrent", exc_info=True)
        return {}


def _download_to_dict(download: Download, qbit_data: dict | None = None) -> dict:
    """Convert a Download model to API response dict with optional live data."""
    result = {
        "id": download.id,
        "book_id": download.book_id,
        "book": {
            "id": download.book.id,
            "title": download.book.title,
            "author": download.book.author.name if download.book.author else None,
            "cover_url": download.book.cover_url,
        }
        if download.book
        else None,
        "torrent_hash": download.torrent_hash,
        "torrent_name": download.torrent_name,
        "indexer_name": download.indexer_name,
        "size": download.size,
        "seeders": download.seeders,
        "status": download.status,
        "file_path": download.file_path,
        "error_message": download.error_message,
        "created_at": download.created_at.isoformat() if download.created_at else None,
        "completed_at": download.completed_at.isoformat() if download.completed_at else None,
        "progress": 1.0 if download.status in (DownloadStatus.COMPLETED, DownloadStatus.IMPORTED) else 0.0,
        "download_speed": 0,
        "eta": 0,
    }

    if qbit_data:
        result["progress"] = qbit_data.get("progress", result["progress"])
        result["download_speed"] = qbit_data.get("dlspeed", 0)
        result["eta"] = qbit_data.get("eta", 0)
        result["size"] = qbit_data.get("total_size", download.size)

    return result


@router.get("")
async def list_downloads(
    status: str | None = Query(default=None, description="Filter by download status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List all downloads with status, progress, and book info.

    Returns live progress data from qBittorrent for active downloads.
    """
    query = db.query(Download).options(joinedload(Download.book).joinedload(Book.author))

    if status:
        if status not in [s.value for s in DownloadStatus]:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        query = query.filter(Download.status == status)

    total = query.count()

    downloads = query.order_by(Download.created_at.desc()).offset(offset).limit(limit).all()

    qbit_client = _get_qbit_client()
    qbit_data = _enrich_with_qbit_data(downloads, qbit_client)

    return {
        "downloads": [_download_to_dict(d, qbit_data.get(d.torrent_hash)) for d in downloads],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/{download_id}")
async def cancel_download(
    download_id: int,
    delete_files: bool = Query(default=True, description="Also delete downloaded files from disk"),
    db: Session = Depends(get_db),
):
    """
    Cancel a download and remove it from qBittorrent.

    Updates the associated book status back to WANTED so it can be retried.
    """
    download = db.query(Download).options(joinedload(Download.book)).filter(Download.id == download_id).first()
    if not download:
        raise HTTPException(status_code=404, detail=f"Download {download_id} not found")

    if download.status in (DownloadStatus.IMPORTED,):
        raise HTTPException(status_code=409, detail="Cannot cancel an already imported download")

    qbit_removed = False
    if download.torrent_hash:
        qbit_client = _get_qbit_client()
        if qbit_client:
            try:
                qbit_removed = qbit_client.delete_torrent(download.torrent_hash, delete_files=delete_files)
            except Exception:
                logger.warning(f"Failed to remove torrent {download.torrent_hash} from qBittorrent", exc_info=True)

    download.status = DownloadStatus.FAILED
    download.error_message = "Cancelled by user"

    if download.book and download.book.status in (
        BookStatus.GRABBED,
        BookStatus.DOWNLOADING,
    ):
        download.book.status = BookStatus.WANTED

    db.commit()

    return {
        "success": True,
        "message": f"Download {download_id} cancelled",
        "qbit_removed": qbit_removed,
    }
