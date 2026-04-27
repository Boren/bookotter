"""
Root Folder API routes.
Handles CRUD operations for root folders where books are stored.
"""

import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.book import RootFolder

router = APIRouter()


def _get_free_space(path: str) -> int | None:
    """Get free space in bytes for a given path."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _get_total_space(path: str) -> int | None:
    """Get total space in bytes for a given path."""
    try:
        return shutil.disk_usage(path).total
    except OSError:
        return None


class RootFolderCreate(BaseModel):
    """Request body for creating a root folder."""

    name: str
    path: str
    folder_organization: str = "flat"


class RootFolderUpdate(BaseModel):
    """Request body for updating a root folder."""

    name: str | None = None
    path: str | None = None
    folder_organization: str | None = None


@router.get("")
async def list_root_folders(db: Session = Depends(get_db)):
    """
    List all root folders.

    Returns a list of all configured root folders.
    """
    folders = db.query(RootFolder).order_by(RootFolder.created_at.desc()).all()

    return {
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "path": f.path,
                "folder_organization": f.folder_organization,
                "created_at": f.created_at.isoformat(),
                "free_space_bytes": _get_free_space(f.path),
                "total_space_bytes": _get_total_space(f.path),
            }
            for f in folders
        ],
        "total": len(folders),
    }


@router.post("")
async def create_root_folder(
    body: RootFolderCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new root folder.

    Args:
        name: Display name for the folder
        path: Absolute filesystem path to the folder
        folder_organization: How to organize books (flat, author, series, author_series)
    """
    # Check if path already exists
    existing = db.query(RootFolder).filter(RootFolder.path == body.path).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Root folder with path '{body.path}' already exists")

    # Create directory if it doesn't exist
    try:
        os.makedirs(body.path, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot create directory '{body.path}': {e}")

    folder = RootFolder(
        name=body.name,
        path=body.path,
        folder_organization=body.folder_organization,
    )

    db.add(folder)
    db.commit()
    db.refresh(folder)

    return {
        "id": folder.id,
        "name": folder.name,
        "path": folder.path,
        "folder_organization": folder.folder_organization,
        "created_at": folder.created_at.isoformat(),
    }


@router.get("/{folder_id}")
async def get_root_folder(folder_id: int, db: Session = Depends(get_db)):
    """Get details of a specific root folder."""
    folder = db.query(RootFolder).filter(RootFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail=f"Root folder {folder_id} not found")

    return {
        "id": folder.id,
        "name": folder.name,
        "path": folder.path,
        "folder_organization": folder.folder_organization,
        "created_at": folder.created_at.isoformat(),
    }


@router.put("/{folder_id}")
async def update_root_folder(
    folder_id: int,
    body: RootFolderUpdate,
    db: Session = Depends(get_db),
):
    """Update a root folder."""
    folder = db.query(RootFolder).filter(RootFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail=f"Root folder {folder_id} not found")

    # Prevent path changes after creation
    if body.path and body.path != folder.path:
        raise HTTPException(status_code=400, detail="Root folder path cannot be changed after creation")

    if body.name:
        folder.name = body.name

    if body.folder_organization:
        folder.folder_organization = body.folder_organization

    db.commit()
    db.refresh(folder)

    return {
        "id": folder.id,
        "name": folder.name,
        "path": folder.path,
        "folder_organization": folder.folder_organization,
        "created_at": folder.created_at.isoformat(),
    }


@router.delete("/{folder_id}")
async def delete_root_folder(folder_id: int, db: Session = Depends(get_db)):
    """Delete a root folder."""
    folder = db.query(RootFolder).filter(RootFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail=f"Root folder {folder_id} not found")

    db.delete(folder)
    db.commit()

    return {"success": True, "message": f"Root folder {folder_id} deleted"}
