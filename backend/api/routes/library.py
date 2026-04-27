"""
Library API routes.
Handles book CRUD operations and browsing with filtering/pagination.
"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models.book import Author, Book, BookStatus, RootFolder
from backend.services.epub_service import EpubMetadata, EpubService

logger = logging.getLogger(__name__)

router = APIRouter()


class BookCreateRequest(BaseModel):
    title: str
    author_name: str | None = None
    hardcover_id: str | None = None
    isbn: str | None = None
    description: str | None = None
    publisher: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    status: str = BookStatus.WANTED.value


class BookUpdateRequest(BaseModel):
    title: str | None = None
    author_name: str | None = None
    hardcover_id: str | None = None
    isbn: str | None = None
    description: str | None = None
    publisher: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    rating: float | None = None
    cover_url: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    status: str | None = None


def _resolve_author(db: Session, author_name: str | None) -> Author | None:
    if not author_name:
        return None
    author = db.query(Author).filter(Author.name == author_name).first()
    if not author:
        author = Author(name=author_name)
        db.add(author)
        db.flush()
    return author


@router.get("/books")
async def list_books(
    status: str | None = Query(default=None, description="Filter by book status"),
    author: str | None = Query(default=None, description="Filter by author name (partial match)"),
    search: str | None = Query(default=None, description="Search title or author"),
    sort_by: str = Query(default="created_at", pattern="^(title|created_at|updated_at|status)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Book).options(joinedload(Book.author))

    if status:
        query = query.filter(Book.status == status)

    if author:
        query = query.join(Author).filter(Author.name.ilike(f"%{author}%"))

    if search:
        search_term = f"%{search}%"
        query = query.outerjoin(Author).filter((Book.title.ilike(search_term)) | (Author.name.ilike(search_term)))

    total = query.count()

    sort_column = getattr(Book, sort_by)
    if sort_order == "desc":
        sort_column = sort_column.desc()
    query = query.order_by(sort_column)

    books = query.offset(offset).limit(limit).all()

    return {
        "books": [b.to_dict() for b in books],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/authors")
async def list_authors(db: Session = Depends(get_db)):
    """List all authors with their book count."""
    authors = db.query(Author).all()
    return {
        "authors": [
            {
                "id": a.id,
                "name": a.name,
                "hardcover_id": a.hardcover_id,
                "book_count": len(a.books),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in authors
        ],
        "total": len(authors),
    }


@router.get("/stats")
async def get_library_stats(db: Session = Depends(get_db)):
    """Get library statistics: total books by status, author count, total size."""
    total_books = db.query(Book).count()

    status_counts = {}
    for status in BookStatus:
        count = db.query(Book).filter(Book.status == status.value).count()
        status_counts[status.value] = count

    author_count = db.query(Author).count()

    total_size = (
        db.query(func.sum(Book.file_size))
        .filter(Book.status == BookStatus.IN_LIBRARY.value, Book.file_size.isnot(None))
        .scalar()
        or 0
    )

    return {
        "total_books": total_books,
        "by_status": status_counts,
        "author_count": author_count,
        "total_size_bytes": total_size,
    }


@router.get("/books/{book_id}")
async def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
    return book.to_dict()


@router.post("/books", status_code=201)
async def create_book(body: BookCreateRequest, db: Session = Depends(get_db)):
    if body.status and body.status not in [s.value for s in BookStatus]:
        raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")

    author = _resolve_author(db, body.author_name)

    book = Book(
        title=body.title,
        author_id=author.id if author else None,
        hardcover_id=body.hardcover_id,
        isbn=body.isbn,
        description=body.description,
        publisher=body.publisher,
        language=body.language,
        tags=body.tags,
        cover_url=body.cover_url,
        series_name=body.series_name,
        series_position=body.series_position,
        status=body.status,
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    return book.to_dict()


@router.put("/books/{book_id}")
async def update_book(book_id: int, body: BookUpdateRequest, db: Session = Depends(get_db)):
    book = db.query(Book).options(joinedload(Book.author)).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    update_data = body.model_dump(exclude_unset=True)

    if "author_name" in update_data:
        author = _resolve_author(db, update_data.pop("author_name"))
        book.author_id = author.id if author else None
    else:
        update_data.pop("author_name", None)

    if "status" in update_data and update_data["status"] not in [s.value for s in BookStatus]:
        raise HTTPException(status_code=422, detail=f"Invalid status: {update_data['status']}")

    for field, value in update_data.items():
        setattr(book, field, value)

    book.updated_at = datetime.utcnow()

    if book.file_path and book.root_folder_id:
        try:
            root_folder = db.query(RootFolder).filter(RootFolder.id == book.root_folder_id).first()
            if root_folder:
                epub_path = os.path.join(root_folder.path, book.file_path)
                if os.path.exists(epub_path):
                    author_name = book.author.name if book.author else None
                    metadata = EpubMetadata(
                        title=book.title,
                        authors=[author_name] if author_name else [],
                        series=book.series_name,
                        series_position=book.series_position,
                        description=book.description,
                        publisher=book.publisher,
                        language=book.language,
                    )
                    EpubService().write_metadata(epub_path, metadata)
        except Exception as e:
            logger.warning("Failed to write EPUB metadata for book %s: %s", book_id, e)

    db.commit()
    db.refresh(book)

    return book.to_dict()


@router.delete("/books/{book_id}")
async def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    if book.file_path and book.root_folder_id:
        try:
            root_folder = db.query(RootFolder).filter(RootFolder.id == book.root_folder_id).first()
            if root_folder:
                epub_path = os.path.join(root_folder.path, book.file_path)
                if os.path.exists(epub_path):
                    os.remove(epub_path)
                    logger.info("Removed EPUB file: %s", epub_path)
        except Exception as e:
            logger.warning("Failed to remove EPUB file for book %s: %s", book_id, e)

    db.delete(book)
    db.commit()

    return {"success": True, "message": f"Book {book_id} deleted"}
