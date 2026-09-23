"""PDF metadata service — the PDF counterpart to EpubService.

Only the document Info dictionary (/Title, /Author) is read and written; PDFs
carry no series or identifier fields worth trusting.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader, PdfWriter

from backend.constants import EPUB_TITLE_SIMILARITY_THRESHOLD
from backend.models.book import Book
from backend.services.epub_service import EpubMetadata, EpubReadError, EpubValidationError, EpubWriteError
from backend.utils.similarity import author_surname_match, title_similarity

logger = logging.getLogger(__name__)

_AUTHOR_SPLIT_RE = re.compile(r"\s*(?:;|&|\band\b)\s*", re.IGNORECASE)


def _split_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in _AUTHOR_SPLIT_RE.split(raw) if part.strip()]


class PdfService:
    """
    Service for reading and writing PDF Info metadata.

    Write pattern mirrors EpubService: clone into a temp file in the same
    directory, re-read to verify the round-trip, then os.replace().
    """

    def read_metadata(self, pdf_path: str | Path) -> EpubMetadata:
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise EpubReadError(f"PDF file not found: {pdf_path}")

        try:
            reader = PdfReader(pdf_path)
        except Exception as e:
            raise EpubReadError(f"Failed to read PDF {pdf_path}: {e}") from e

        if reader.is_encrypted:
            raise EpubReadError(f"PDF is encrypted, cannot read metadata: {pdf_path}")

        return self._extract_metadata(reader)

    def write_metadata(
        self,
        pdf_path: str | Path,
        metadata: EpubMetadata,
        output_path: str | Path | None = None,
    ) -> Path:
        pdf_path = Path(pdf_path)
        target_path = Path(output_path) if output_path else pdf_path

        if not pdf_path.exists():
            raise EpubReadError(f"PDF file not found: {pdf_path}")

        try:
            reader = PdfReader(pdf_path)
        except Exception as e:
            raise EpubReadError(f"Failed to read PDF {pdf_path}: {e}") from e

        if reader.is_encrypted:
            raise EpubWriteError(f"PDF is encrypted, cannot write metadata: {pdf_path}")

        info: dict[str, str] = {}
        if metadata.title is not None:
            info["/Title"] = metadata.title
        if metadata.authors:
            info["/Author"] = "; ".join(metadata.authors)

        temp_fd, temp_path_str = tempfile.mkstemp(suffix=".pdf.tmp", dir=target_path.parent)
        os.close(temp_fd)
        temp_path = Path(temp_path_str)

        try:
            try:
                writer = PdfWriter(clone_from=reader)
                writer.add_metadata(info)
                with open(temp_path, "wb") as fh:
                    writer.write(fh)
            except Exception as e:
                raise EpubWriteError(f"Failed to write PDF to temp file: {e}") from e

            self._validate_written_pdf(temp_path, len(reader.pages), metadata)
            os.replace(temp_path, target_path)
            logger.info("Successfully wrote metadata to %s", target_path)

        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

        return target_path

    def validate(self, pdf_path: str | Path) -> bool:
        pdf_path = Path(pdf_path)

        if not pdf_path.is_file():
            return False

        try:
            with open(pdf_path, "rb") as fh:
                if not fh.read(1024).lstrip().startswith(b"%PDF-"):
                    return False
            reader = PdfReader(pdf_path)
            if reader.is_encrypted:
                # Encrypted PDFs are still valid books — DRM handling happens later.
                return True
            return len(reader.pages) > 0
        except Exception:
            return False

    def is_drm_protected(self, pdf_path: str | Path) -> bool:
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return False

        try:
            return PdfReader(pdf_path).is_encrypted
        except Exception:
            return False

    def verify_content(self, pdf_path: Path, expected_book: Book) -> tuple[bool, str | None]:
        """Soft content verification. Most PDFs carry no metadata, so empty means 'can't tell', not 'wrong'."""
        try:
            metadata = self.read_metadata(pdf_path)
        except Exception:
            return (True, None)

        if not metadata.title and not metadata.authors:
            return (True, None)

        expected_title = cast(str | None, expected_book.title)
        expected_author = cast(Any, expected_book.author)
        expected_author_names = [cast(str, expected_author.name)] if expected_author is not None else []

        title_sim = title_similarity(metadata.title or "", expected_title or "")
        author_match = author_surname_match(metadata.authors, expected_author_names)

        if title_sim >= EPUB_TITLE_SIMILARITY_THRESHOLD or author_match:
            return (True, None)

        return (False, f"low_confidence: title_sim={title_sim:.2f}, author_match={author_match}")

    def _extract_metadata(self, reader: PdfReader) -> EpubMetadata:
        meta = EpubMetadata()
        info = reader.metadata
        if info is None:
            return meta

        title = info.title
        if title and title.strip():
            meta.title = title.strip()
        meta.authors = _split_authors(info.author)
        return meta

    def _validate_written_pdf(self, temp_path: Path, original_page_count: int, expected: EpubMetadata) -> None:
        try:
            reader = PdfReader(temp_path)
        except Exception as e:
            raise EpubValidationError(f"Cannot re-read written PDF: {e}") from e

        if len(reader.pages) != original_page_count:
            raise EpubValidationError(
                f"Page count mismatch after write: original={original_page_count}, written={len(reader.pages)}"
            )

        info = reader.metadata
        written_title = info.title if info is not None else None
        written_author = info.author if info is not None else None
        if expected.title is not None and written_title != expected.title:
            raise EpubValidationError(f"Title mismatch after write: expected={expected.title!r}, got={written_title!r}")
        if expected.authors and written_author != "; ".join(expected.authors):
            raise EpubValidationError(f"Authors mismatch: expected={expected.authors!r}, got={written_author!r}")
