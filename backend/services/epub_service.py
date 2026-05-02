"""EPUB metadata service with safe read/write operations for BookOtter."""

import logging
import os
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ebooklib import epub

from backend.constants import EPUB_TITLE_SIMILARITY_THRESHOLD
from backend.models.book import Book
from backend.utils.similarity import author_surname_match, title_similarity

logger = logging.getLogger(__name__)


@dataclass
class EpubMetadata:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    series: str | None = None
    series_position: float | None = None
    language: str | None = None
    publisher: str | None = None
    description: str | None = None
    identifier: str | None = None


class EpubServiceError(Exception):
    pass


class EpubReadError(EpubServiceError):
    pass


class EpubWriteError(EpubServiceError):
    pass


class EpubValidationError(EpubServiceError):
    pass


class EpubService:
    """
    Service for reading and writing EPUB metadata.

    Write pattern (safe, atomic):
      1. Read source EPUB
      2. Apply metadata via correct ebooklib methods
      3. Write to temp file in same directory
      4. Validate temp file (item count + metadata round-trip)
      5. os.replace() — atomic on POSIX
    """

    def read_metadata(self, epub_path: str | Path) -> EpubMetadata:
        epub_path = Path(epub_path)

        if not epub_path.exists():
            raise EpubReadError(f"EPUB file not found: {epub_path}")

        if self.is_drm_protected(epub_path):
            raise EpubReadError(f"EPUB is DRM-protected, cannot read metadata: {epub_path}")

        try:
            book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        except Exception as e:
            raise EpubReadError(f"Failed to read EPUB {epub_path}: {e}") from e

        return self._extract_metadata(book)

    def write_metadata(
        self,
        epub_path: str | Path,
        metadata: EpubMetadata,
        output_path: str | Path | None = None,
    ) -> Path:
        epub_path = Path(epub_path)
        target_path = Path(output_path) if output_path else epub_path

        if not epub_path.exists():
            raise EpubReadError(f"EPUB file not found: {epub_path}")

        if self.is_drm_protected(epub_path):
            raise EpubWriteError(f"EPUB is DRM-protected, cannot write metadata: {epub_path}")

        try:
            book = epub.read_epub(str(epub_path))
        except Exception as e:
            raise EpubReadError(f"Failed to read EPUB {epub_path}: {e}") from e

        original_item_count = len(list(book.get_items()))
        self._apply_metadata(book, metadata)
        self._ensure_toc_uids(book.toc)

        temp_fd, temp_path_str = tempfile.mkstemp(suffix=".epub.tmp", dir=target_path.parent)
        os.close(temp_fd)
        temp_path = Path(temp_path_str)

        try:
            try:
                epub.write_epub(str(temp_path), book, {})
            except Exception as e:
                raise EpubWriteError(f"Failed to write EPUB to temp file: {e}") from e

            self._validate_written_epub(temp_path, original_item_count, metadata)
            os.replace(temp_path, target_path)
            logger.info("Successfully wrote metadata to %s", target_path)

        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

        return target_path

    def validate_epub(self, epub_path: str | Path) -> bool:
        epub_path = Path(epub_path)

        if not epub_path.exists():
            return False

        if not zipfile.is_zipfile(epub_path):
            return False

        try:
            with zipfile.ZipFile(epub_path, "r") as zf:
                if "mimetype" not in zf.namelist():
                    return False
                mimetype = zf.read("mimetype").decode("utf-8", errors="replace").strip()
                if mimetype != "application/epub+zip":
                    return False
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
            return False

        try:
            epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        except Exception:
            return False

        return True

    def is_drm_protected(self, epub_path: str | Path) -> bool:
        """Detect DRM via presence of META-INF/encryption.xml (Adobe DRM / LCP standard)."""
        epub_path = Path(epub_path)

        if not epub_path.exists():
            return False

        try:
            with zipfile.ZipFile(epub_path, "r") as zf:
                return "META-INF/encryption.xml" in zf.namelist()
        except (zipfile.BadZipFile, OSError):
            return False

    def verify_content(self, epub_path: Path, expected_book: Book) -> tuple[bool, str | None]:
        """Soft content verification for imported EPUBs."""
        try:
            book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
            metadata = self._extract_metadata(book)
        except Exception:
            return (False, "could not extract EPUB metadata")

        if isinstance(metadata, Mapping):
            epub_title = metadata.get("title", "") or ""
            epub_authors = metadata.get("authors", []) or []
            epub_isbns = metadata.get("isbns", []) or []
        else:
            epub_title = metadata.title or ""
            epub_authors = metadata.authors or []
            epub_isbns = [metadata.identifier] if metadata.identifier else []

        expected_isbn = cast(str | None, expected_book.isbn)
        expected_title = cast(str | None, expected_book.title)
        expected_author = cast(Any, expected_book.author)
        expected_author_names = [cast(str, expected_author.name)] if expected_author is not None else []

        if expected_isbn and expected_isbn in epub_isbns:
            return (True, None)

        title_sim = title_similarity(epub_title, expected_title or "")
        author_match = author_surname_match(epub_authors, expected_author_names)

        if title_sim >= EPUB_TITLE_SIMILARITY_THRESHOLD or author_match:
            return (True, None)

        return (False, f"low_confidence: title_sim={title_sim:.2f}, author_match={author_match}")

    def _extract_metadata(self, book: epub.EpubBook) -> EpubMetadata:
        meta = EpubMetadata()

        titles = book.get_metadata("DC", "title")
        if titles:
            meta.title = titles[0][0]

        creators = book.get_metadata("DC", "creator")
        meta.authors = [c[0] for c in creators if c[0]]

        langs = book.get_metadata("DC", "language")
        if langs:
            meta.language = langs[0][0]

        publishers = book.get_metadata("DC", "publisher")
        if publishers:
            meta.publisher = publishers[0][0]

        descriptions = book.get_metadata("DC", "description")
        if descriptions:
            meta.description = descriptions[0][0]

        identifiers = book.get_metadata("DC", "identifier")
        if identifiers:
            meta.identifier = identifiers[0][0]

        _OPF_NS = "http://www.idpf.org/2007/opf"
        all_opf_meta = book.metadata.get(None, {}).get("meta", []) + book.metadata.get(_OPF_NS, {}).get("meta", [])
        for _value, attrs in all_opf_meta:
            name = attrs.get("name", "")
            content = attrs.get("content", "")
            if name == "calibre:series" and content:
                meta.series = content
            elif name == "calibre:series_index" and content:
                try:
                    meta.series_position = float(content)
                except ValueError:
                    pass

        return meta

    def _apply_metadata(self, book: epub.EpubBook, metadata: EpubMetadata) -> None:
        if metadata.title is not None:
            book.set_unique_metadata("DC", "title", metadata.title)

        if metadata.authors:
            book.metadata.get("DC", {}).pop("creator", None)
            if len(metadata.authors) == 1:
                book.set_unique_metadata("DC", "creator", metadata.authors[0])
            else:
                for author in metadata.authors:
                    book.add_metadata("DC", "creator", author, {})

        if metadata.language is not None:
            book.set_unique_metadata("DC", "language", metadata.language)

        if metadata.publisher is not None:
            book.set_unique_metadata("DC", "publisher", metadata.publisher)

        if metadata.description is not None:
            book.set_unique_metadata("DC", "description", metadata.description)

        if metadata.series is not None:
            self._set_calibre_meta(book, "calibre:series", metadata.series)

        if metadata.series_position is not None:
            pos = metadata.series_position
            pos_str = str(int(pos)) if pos == int(pos) else str(pos)
            self._set_calibre_meta(book, "calibre:series_index", pos_str)

    def _set_calibre_meta(self, book: epub.EpubBook, name: str, value: str) -> None:
        _OPF_NS = "http://www.idpf.org/2007/opf"
        for ns in (None, _OPF_NS):
            existing = book.metadata.get(ns, {}).get("meta", [])
            if existing:
                book.metadata.setdefault(ns, {})["meta"] = [(v, a) for v, a in existing if a.get("name") != name]
        book.add_metadata(None, "meta", "", {"name": name, "content": value})

    def _validate_written_epub(
        self,
        temp_path: Path,
        original_item_count: int,
        expected_metadata: EpubMetadata,
        expected_item_delta: int = 0,
    ) -> None:
        if not self.validate_epub(temp_path):
            raise EpubValidationError(f"Written EPUB failed basic validation: {temp_path}")

        try:
            written_book = epub.read_epub(str(temp_path))
        except Exception as e:
            raise EpubValidationError(f"Cannot re-read written EPUB: {e}") from e

        written_item_count = len(list(written_book.get_items()))
        if written_item_count != original_item_count + expected_item_delta:
            raise EpubValidationError(
                f"Item count mismatch after write: original={original_item_count}, "
                f"written={written_item_count}, expected_delta={expected_item_delta}"
            )

        written_meta = self._extract_metadata(written_book)

        if expected_metadata.title is not None and written_meta.title != expected_metadata.title:
            raise EpubValidationError(
                f"Title mismatch after write: expected={expected_metadata.title!r}, got={written_meta.title!r}"
            )

        if expected_metadata.authors and written_meta.authors != expected_metadata.authors:
            raise EpubValidationError(
                f"Authors mismatch: expected={expected_metadata.authors!r}, got={written_meta.authors!r}"
            )

    def _ensure_toc_uids(self, toc: list | tuple, _counter: list | None = None) -> None:
        if _counter is None:
            _counter = [0]
        for item in toc:
            if isinstance(item, (tuple, list)):
                self._ensure_toc_uids(item, _counter)
            elif hasattr(item, "uid") and item.uid is None:
                item.uid = f"toc-item-{_counter[0]}"
                _counter[0] += 1
