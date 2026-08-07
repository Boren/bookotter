"""
E-reader management API routes.
Handles CRUD operations for E-reader device configurations.
"""

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.routes.browse import BrowseResponse
from backend.clients.ereader_client import (
    EreaderClient,
    EreaderConnectionError,
    EreaderNotFoundError,
    EreaderPermissionError,
    EreaderTimeoutError,
)
from backend.config import (
    add_ereader,
    delete_ereader,
    get_all_ereaders,
    get_ereader_by_id,
    mask_sensitive_data,
    update_ereader,
)
from backend.database import get_db
from backend.models.book import Book

router = APIRouter()

# Reachability cache: ereader_id -> (monotonic_checked_at, reachable, checked_at_iso).
# The TCP probe takes up to 3s; the dashboard widget and E-reader page poll this
# endpoint, so cache briefly to avoid hammering a sleeping device.
_status_cache: dict[str, tuple[float, bool, str]] = {}
STATUS_CACHE_TTL_SECONDS = 10.0


class EreaderCreate(BaseModel):
    """Request body for creating a E-reader."""

    name: str
    hostname: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    ssh_key_path: str | None = None
    destination_path: str = "/mnt/us/books/"


class EreaderUpdate(BaseModel):
    """Request body for updating a E-reader."""

    name: str | None = None
    hostname: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    ssh_key_path: str | None = None
    destination_path: str | None = None


@router.get("")
async def list_ereaders():
    """List all configured E-reader devices."""
    ereaders = get_all_ereaders()
    # Mask sensitive data in response
    return [mask_sensitive_data(k) for k in ereaders]


@router.get("/{ereader_id}")
async def get_ereader(ereader_id: str):
    """Get a specific E-reader configuration."""
    ereader = get_ereader_by_id(ereader_id)
    if not ereader:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")
    return mask_sensitive_data(ereader)


@router.post("")
async def create_ereader(body: EreaderCreate):
    """Create a new E-reader configuration."""
    # Generate unique ID
    ereader_id = str(uuid.uuid4())[:8]

    ereader_config = {
        "id": ereader_id,
        "name": body.name,
        "hostname": body.hostname,
        "port": body.port,
        "username": body.username,
        "password": body.password or "",
        "ssh_key_path": body.ssh_key_path or "",
        "destination_path": body.destination_path,
    }

    try:
        added = add_ereader(ereader_config)
        return {"success": True, "ereader": mask_sensitive_data(added)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{ereader_id}")
async def update_ereader_endpoint(ereader_id: str, body: EreaderUpdate):
    """Update a E-reader configuration."""
    # Build updates dict, excluding None values
    updates: dict[str, str | int] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.hostname is not None:
        updates["hostname"] = body.hostname
    if body.port is not None:
        updates["port"] = body.port
    if body.username is not None:
        updates["username"] = body.username
    if body.password is not None and body.password != "***MASKED***":
        updates["password"] = body.password
    if body.ssh_key_path is not None:
        updates["ssh_key_path"] = body.ssh_key_path
    if body.destination_path is not None:
        updates["destination_path"] = body.destination_path

    result = update_ereader(ereader_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")

    return {"success": True, "ereader": mask_sensitive_data(result)}


@router.delete("/{ereader_id}")
async def delete_ereader_endpoint(ereader_id: str):
    """Delete a E-reader configuration."""
    if delete_ereader(ereader_id):
        return {"success": True, "message": f"E-reader '{ereader_id}' deleted"}
    else:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")


@router.post("/{ereader_id}/test")
async def test_ereader_endpoint(ereader_id: str):
    """Test SSH connection to a E-reader."""
    ereader_config = get_ereader_by_id(ereader_id)
    if not ereader_config:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")

    if not ereader_config.get("hostname"):
        return {"success": False, "error": "Hostname not configured"}

    try:
        client = EreaderClient.from_config(ereader_config)
        result = client.test_connection()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/{ereader_id}/status")
async def get_ereader_status(ereader_id: str, refresh: bool = False):
    """Reachability of a E-reader device (cached TCP probe, no SSH handshake)."""
    ereader_config = get_ereader_by_id(ereader_id)
    if not ereader_config:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")

    base = {
        "ereader_id": ereader_id,
        "name": ereader_config.get("name", ""),
        "hostname": ereader_config.get("hostname", ""),
    }

    if not ereader_config.get("hostname"):
        return {**base, "configured": False, "reachable": False, "checked_at": None, "cached": False}

    cached = _status_cache.get(ereader_id)
    if cached and not refresh and (time.monotonic() - cached[0]) < STATUS_CACHE_TTL_SECONDS:
        return {**base, "configured": True, "reachable": cached[1], "checked_at": cached[2], "cached": True}

    client = EreaderClient.from_config(ereader_config)
    reachable = await asyncio.to_thread(client.is_reachable)
    checked_at = datetime.now(UTC).isoformat()
    _status_cache[ereader_id] = (time.monotonic(), reachable, checked_at)
    return {**base, "configured": True, "reachable": reachable, "checked_at": checked_at, "cached": False}


@router.get("/{ereader_id}/books")
async def list_ereader_books(ereader_id: str, db: Session = Depends(get_db)):
    """List books currently on a E-reader, matched to library books by filename."""
    ereader_config = get_ereader_by_id(ereader_id)
    if not ereader_config:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")

    try:
        client = EreaderClient.from_config(ereader_config)
        books = client.list_books()
    except Exception as e:
        return {"success": False, "error": str(e), "books": []}

    # Files are uploaded with their local basename unchanged, so
    # basename(Book.file_path) is an exact join key (same as the sync code).
    rows = db.query(Book.id, Book.title, Book.file_path).filter(Book.file_path.isnot(None)).all()
    by_basename = {os.path.basename(file_path): (book_id, title) for book_id, title, file_path in rows}
    for file in books:
        file["book_id"], file["title"] = by_basename.get(file["name"], (None, None))

    return {"success": True, "books": books, "count": len(books)}


@router.get("/{ereader_id}/browse", response_model=BrowseResponse)
async def browse_ereader_directory(ereader_id: str, path: str, show_hidden: bool = False):
    ereader_config = get_ereader_by_id(ereader_id)
    if not ereader_config:
        raise HTTPException(status_code=404, detail=f"E-reader '{ereader_id}' not found")

    try:
        client = EreaderClient.from_config(ereader_config)
        return client.list_directory(path, show_hidden=show_hidden, max_entries=1000)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except EreaderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except EreaderPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except EreaderTimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except EreaderConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
