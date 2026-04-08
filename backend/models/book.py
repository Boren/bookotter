"""
Database models for books, authors, root folders, and downloads.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class BookStatus(StrEnum):
    """Status of a book in the library pipeline."""

    WANTED = "wanted"
    SEARCHING = "searching"
    GRABBED = "grabbed"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    IN_LIBRARY = "in_library"
    FAILED = "failed"


class DownloadStatus(StrEnum):
    """Status of a download/torrent."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    IMPORTING = "importing"
    IMPORTED = "imported"
    FAILED = "failed"


class FolderOrganization(StrEnum):
    """How to organize books in root folder."""

    FLAT = "flat"
    AUTHOR = "author"
    SERIES = "series"
    AUTHOR_SERIES = "author_series"


# Association table for many-to-many relationship (future-proofing)
book_author_association = Table(
    "book_author",
    Base.metadata,
    Column("book_id", Integer, ForeignKey("book.id"), primary_key=True),
    Column("author_id", Integer, ForeignKey("author.id"), primary_key=True),
)


class Author(Base):
    """Represents a book author."""

    __tablename__ = "author"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(500), nullable=False)
    hardcover_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    books = relationship("Book", back_populates="author")

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "hardcover_id": self.hardcover_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RootFolder(Base):
    """Represents a root folder where books are stored."""

    __tablename__ = "root_folder"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    path = Column(String(1000), nullable=False, unique=True)
    folder_organization = Column(String(20), nullable=False, default=FolderOrganization.FLAT.value)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    books = relationship("Book", back_populates="root_folder")


class Book(Base):
    """Represents a book in the library."""

    __tablename__ = "book"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    author_id = Column(Integer, ForeignKey("author.id"), nullable=True, index=True)
    hardcover_id = Column(String(100), nullable=True, index=True)
    isbn = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    publisher = Column(String(255), nullable=True)
    language = Column(String(10), nullable=True)
    tags = Column(JSON, nullable=True)  # List of tags
    rating = Column(Float, nullable=True)
    read_date = Column(DateTime, nullable=True)
    cover_url = Column(String(500), nullable=True)
    series_name = Column(String(255), nullable=True)
    series_position = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default=BookStatus.WANTED.value, index=True)
    root_folder_id = Column(Integer, ForeignKey("root_folder.id"), nullable=True, index=True)
    file_path = Column(String(1000), nullable=True)  # Relative to root folder
    file_size = Column(Integer, nullable=True)  # Bytes
    search_attempts = Column(Integer, default=0)
    last_searched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    author = relationship("Author", back_populates="books")
    root_folder = relationship("RootFolder", back_populates="books")
    downloads = relationship("Download", back_populates="book", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (Index("ix_book_status_created", "status", "created_at"),)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "title": self.title,
            "author_id": self.author_id,
            "author": self.author.to_dict() if self.author else None,
            "hardcover_id": self.hardcover_id,
            "isbn": self.isbn,
            "description": self.description,
            "publisher": self.publisher,
            "language": self.language,
            "tags": self.tags,
            "rating": self.rating,
            "read_date": self.read_date.isoformat() if self.read_date else None,
            "cover_url": self.cover_url,
            "series_name": self.series_name,
            "series_position": self.series_position,
            "status": self.status,
            "root_folder_id": self.root_folder_id,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "search_attempts": self.search_attempts,
            "last_searched_at": self.last_searched_at.isoformat() if self.last_searched_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Download(Base):
    """Represents a download/torrent for a book."""

    __tablename__ = "download"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("book.id"), nullable=False, index=True)
    torrent_hash = Column(String(100), nullable=False, unique=True, index=True)
    torrent_name = Column(String(500), nullable=False)
    indexer_name = Column(String(100), nullable=False)
    download_url = Column(String(1000), nullable=False)
    size = Column(Integer, nullable=False)  # Bytes
    seeders = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=DownloadStatus.QUEUED.value, index=True)
    file_path = Column(String(1000), nullable=True)  # EPUB path within torrent
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    book = relationship("Book", back_populates="downloads")

    # Indexes
    __table_args__ = (Index("ix_download_status_created", "status", "created_at"),)
