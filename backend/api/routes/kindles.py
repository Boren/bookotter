"""
Kindle management API routes.
Handles CRUD operations for Kindle device configurations.
"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.routes.browse import BrowseResponse
from backend.clients.kindle_client import (
    KindleClient,
    KindleConnectionError,
    KindleNotFoundError,
    KindlePermissionError,
    KindleTimeoutError,
)
from backend.config import (
    add_kindle,
    delete_kindle,
    get_all_kindles,
    get_kindle_by_id,
    mask_sensitive_data,
    update_kindle,
)

router = APIRouter()


class KindleCreate(BaseModel):
    """Request body for creating a Kindle."""

    name: str
    hostname: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    ssh_key_path: str | None = None
    destination_path: str = "/mnt/us/books/"


class KindleUpdate(BaseModel):
    """Request body for updating a Kindle."""

    name: str | None = None
    hostname: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    ssh_key_path: str | None = None
    destination_path: str | None = None


@router.get("")
async def list_kindles():
    """List all configured Kindle devices."""
    kindles = get_all_kindles()
    # Mask sensitive data in response
    return [mask_sensitive_data(k) for k in kindles]


@router.get("/{kindle_id}")
async def get_kindle(kindle_id: str):
    """Get a specific Kindle configuration."""
    kindle = get_kindle_by_id(kindle_id)
    if not kindle:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")
    return mask_sensitive_data(kindle)


@router.post("")
async def create_kindle(body: KindleCreate):
    """Create a new Kindle configuration."""
    # Generate unique ID
    kindle_id = str(uuid.uuid4())[:8]

    kindle_config = {
        "id": kindle_id,
        "name": body.name,
        "hostname": body.hostname,
        "port": body.port,
        "username": body.username,
        "password": body.password or "",
        "ssh_key_path": body.ssh_key_path or "",
        "destination_path": body.destination_path,
    }

    try:
        added = add_kindle(kindle_config)
        return {"success": True, "kindle": mask_sensitive_data(added)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{kindle_id}")
async def update_kindle_endpoint(kindle_id: str, body: KindleUpdate):
    """Update a Kindle configuration."""
    # Build updates dict, excluding None values
    updates = {}
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

    result = update_kindle(kindle_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")

    return {"success": True, "kindle": mask_sensitive_data(result)}


@router.delete("/{kindle_id}")
async def delete_kindle_endpoint(kindle_id: str):
    """Delete a Kindle configuration."""
    if delete_kindle(kindle_id):
        return {"success": True, "message": f"Kindle '{kindle_id}' deleted"}
    else:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")


@router.post("/{kindle_id}/test")
async def test_kindle_endpoint(kindle_id: str):
    """Test SSH connection to a Kindle."""
    kindle_config = get_kindle_by_id(kindle_id)
    if not kindle_config:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")

    if not kindle_config.get("hostname"):
        return {"success": False, "error": "Hostname not configured"}

    try:
        client = KindleClient.from_config(kindle_config)
        result = client.test_connection()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/{kindle_id}/books")
async def list_kindle_books(kindle_id: str):
    """List books currently on a Kindle."""
    kindle_config = get_kindle_by_id(kindle_id)
    if not kindle_config:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")

    try:
        client = KindleClient.from_config(kindle_config)
        books = client.list_books()
        return {"success": True, "books": books, "count": len(books)}
    except Exception as e:
        return {"success": False, "error": str(e), "books": []}


@router.get("/{kindle_id}/browse", response_model=BrowseResponse)
async def browse_kindle_directory(kindle_id: str, path: str, show_hidden: bool = False):
    kindle_config = get_kindle_by_id(kindle_id)
    if not kindle_config:
        raise HTTPException(status_code=404, detail=f"Kindle '{kindle_id}' not found")

    try:
        client = KindleClient.from_config(kindle_config)
        return client.list_directory(path, show_hidden=show_hidden, max_entries=1000)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KindleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except KindlePermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except KindleTimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except KindleConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
