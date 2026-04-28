"""Wanted/missing queue API routes."""

from typing import cast

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models.book import Book, BookStatus
from backend.services.pipeline_states import transition_book

router = APIRouter()


@router.get("/missing")
async def list_missing_books(db: Session = Depends(get_db)):
    """List all books currently missing from the library."""
    books = (
        db.query(Book)
        .options(joinedload(Book.author))
        .filter(Book.status == BookStatus.MISSING.value)
        .order_by(Book.updated_at.desc())
        .all()
    )
    return {"books": [book.to_dict() for book in books], "total": len(books)}


@router.post("/search-all")
async def search_all_missing(db: Session = Depends(get_db)):
    """Mark all missing books as searching for the next pipeline cycle."""
    books = db.query(Book).filter(Book.status == BookStatus.MISSING.value).all()

    triggered: list[int] = []
    for book in books:
        if transition_book(book, BookStatus.SEARCHING.value):
            triggered.append(cast(int, book.id))

    db.commit()
    return {"triggered": len(triggered), "book_ids": triggered}
