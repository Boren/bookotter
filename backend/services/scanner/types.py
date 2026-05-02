"""Matcher types for library scanner — frozen dataclasses and enums."""

from dataclasses import dataclass
from enum import StrEnum


class MatchMethod(StrEnum):
    """Enumeration of book matching methods."""

    EMBEDDED_HARDCOVER_ID = "embedded_hardcover_id"
    ISBN = "isbn"
    NORMALIZED_EXACT = "normalized_exact"
    FUZZY = "fuzzy"
    FILENAME = "filename"


@dataclass(frozen=True)
class FileMetadata:
    """Immutable metadata extracted from a file in the library."""

    relative_path: str
    size_bytes: int
    title: str | None
    authors: tuple[str, ...]
    identifier: str | None
    isbn: str | None
    series: str | None
    series_position: float | None


@dataclass(frozen=True)
class BookCandidate:
    """Immutable book candidate from the database."""

    id: int
    hardcover_id: str | None
    isbn: str | None
    title: str
    author_name: str | None
    file_path: str | None


@dataclass(frozen=True)
class MatchResult:
    """Immutable result of a match attempt between file and candidate."""

    method: MatchMethod
    candidate_book_id: int
    score: float
    auto_link: bool
