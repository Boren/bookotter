"""Supported book file formats and format-aware helpers.

EPUB is the preferred format; PDF is accepted as a fallback for books that
only exist as PDF. A book's format is derived from its file suffix.
"""

import os
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from backend.constants import EPUB_TITLE_SIMILARITY_THRESHOLD
from backend.utils.similarity import title_similarity

if TYPE_CHECKING:
    from backend.models.book import Book
    from backend.services.epub_service import EpubMetadata


class BookFormat(StrEnum):
    EPUB = "epub"
    PDF = "pdf"


SUPPORTED_SUFFIXES = {f".{fmt.value}" for fmt in BookFormat}

_MEDIA_TYPES = {
    BookFormat.EPUB: "application/epub+zip",
    BookFormat.PDF: "application/pdf",
}


class BookFileService(Protocol):
    """Surface shared by EpubService and PdfService."""

    def read_metadata(self, path: str | Path) -> EpubMetadata: ...

    def write_metadata(
        self, path: str | Path, metadata: EpubMetadata, output_path: str | Path | None = None
    ) -> Path: ...

    def validate(self, path: str | Path) -> bool: ...

    def is_drm_protected(self, path: str | Path) -> bool: ...

    def verify_content(self, path: Path, expected_book: Book) -> tuple[bool, str | None]: ...


def format_of(path: str | Path | None) -> BookFormat | None:
    if not path:
        return None
    suffix = Path(str(path)).suffix.lower().lstrip(".")
    try:
        return BookFormat(suffix)
    except ValueError:
        return None


def is_book_file(path: str | Path) -> bool:
    return format_of(path) is not None


def media_type_for(path: str | Path) -> str:
    fmt = format_of(path)
    return _MEDIA_TYPES[fmt] if fmt else "application/octet-stream"


def service_for(path: str | Path, epub_service: BookFileService, pdf_service: BookFileService) -> BookFileService:
    """Pick the metadata service for a file; anything that isn't a PDF is treated as EPUB."""
    return pdf_service if format_of(path) == BookFormat.PDF else epub_service


def pick_book_file(names: Iterable[str], title: str | None = None, allow_pdf: bool = True) -> str | None:
    """Choose the book file to import from a torrent's file list.

    The first EPUB wins. Otherwise a lone PDF is taken; with several PDFs (an
    ebook pack) only one whose filename clearly matches ``title`` is accepted.
    """
    names = list(names)
    epubs = [n for n in names if format_of(n) == BookFormat.EPUB]
    if epubs:
        return epubs[0]
    if not allow_pdf:
        return None

    pdfs = [n for n in names if format_of(n) == BookFormat.PDF]
    if len(pdfs) == 1:
        return pdfs[0]
    if not pdfs or not title:
        return None

    scored = [(title_similarity(title, os.path.splitext(os.path.basename(n))[0]), n) for n in pdfs]
    best_score, best_name = max(scored)
    return best_name if best_score >= EPUB_TITLE_SIMILARITY_THRESHOLD else None
