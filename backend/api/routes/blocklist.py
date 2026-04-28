from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.blocklist_service import BlocklistService

router = APIRouter()


class BlocklistCreateRequest(BaseModel):
    indexer: str
    release_guid: str
    title: str
    reason: str | None = None


class BlocklistFromReleaseRequest(BaseModel):
    indexer: str
    release_guid: str
    title: str
    reason: str | None = None


@router.get("")
async def list_blocklist(db: Session = Depends(get_db)):
    service = BlocklistService(db)
    entries = service.list_all()
    return {"entries": [entry.to_dict() for entry in entries], "total": len(entries)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_blocklist_entry(body: BlocklistCreateRequest, db: Session = Depends(get_db)):
    service = BlocklistService(db)
    try:
        entry = service.add(
            indexer=body.indexer,
            release_guid=body.release_guid,
            title=body.title,
            reason=body.reason,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Blocklist entry already exists") from exc

    return entry.to_dict()


@router.post("/from-release", status_code=status.HTTP_201_CREATED)
async def blocklist_from_release(body: BlocklistFromReleaseRequest, db: Session = Depends(get_db)):
    """Convenience endpoint: blocklist a release directly from a search result row."""
    service = BlocklistService(db)
    try:
        entry = service.add(
            indexer=body.indexer,
            release_guid=body.release_guid,
            title=body.title,
            reason=body.reason,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Blocklist entry already exists") from exc
    return entry.to_dict()


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocklist_entry(entry_id: int, db: Session = Depends(get_db)):
    service = BlocklistService(db)
    deleted = service.remove(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Blocklist entry {entry_id} not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
