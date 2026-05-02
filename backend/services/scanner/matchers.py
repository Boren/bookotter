"""
Pure-function matcher tiers for library scanner cascade.

Implements three of five matching tiers:
- T10: ISBN matcher (exact match post-hyphen-strip)
- T11: NormalizedExactMatcher (exact match on normalized title + first author)
- T13: FilenameMatcher (last-resort: parse 'Author - Title.epub' from filename)

T9 (EmbeddedHardcoverIdMatcher) and T12 (FuzzyMatcher) will be appended to this
module in later tasks. All matchers follow the same signature and return MatchResult
or None.
"""

import os
import re

from backend.services.scanner.normalize import normalize
from backend.services.scanner.types import (
    BookCandidate,
    FileMetadata,
    MatchMethod,
    MatchResult,
)

# Filename pattern: "Author - Title.epub" (last-resort tier)
FILENAME_PATTERN = re.compile(r"^(?P<author>.+?)\s*-\s*(?P<title>.+?)\.epub$", re.IGNORECASE)


def match_isbn(
    file_meta: FileMetadata,
    candidates_by_isbn: dict[str, BookCandidate],
) -> MatchResult | None:
    """
    Match by ISBN exact (post-hyphen-strip).

    Strips hyphens, spaces, and dashes from both sides before comparison.
    The caller is expected to have already pre-cleaned the dict keys the same way.

    Args:
        file_meta: File metadata including ISBN
        candidates_by_isbn: Dict mapping cleaned ISBN strings to BookCandidate objects

    Returns:
        MatchResult with score 100.0 if ISBN matches, None otherwise
    """
    if file_meta.isbn is None:
        return None

    # Strip non-digit and non-X characters (handles hyphens, spaces, dashes)
    cleaned_isbn = "".join(c for c in file_meta.isbn if c.isdigit() or c.upper() == "X")

    if not cleaned_isbn:
        return None

    candidate = candidates_by_isbn.get(cleaned_isbn)
    if candidate is None:
        return None

    return MatchResult(
        method=MatchMethod.ISBN,
        candidate_book_id=candidate.id,
        score=100.0,
        auto_link=False,
    )


def match_normalized_exact(
    file_meta: FileMetadata,
    candidates_by_normalized_key: dict[tuple[str, str], BookCandidate],
) -> MatchResult | None:
    """
    Match by exact normalized title + first author.

    Normalizes file_meta.title and file_meta.authors[0] via the scanner's
    normalize() function. Looks up (norm_title, norm_author) in the dict.

    Args:
        file_meta: File metadata including title and authors
        candidates_by_normalized_key: Dict mapping (normalized_title, normalized_author) tuples to BookCandidate objects

    Returns:
        MatchResult with score 100.0 if normalized title+author matches, None otherwise
    """
    if file_meta.title is None or len(file_meta.authors) == 0:
        return None

    norm_title = normalize(file_meta.title)
    norm_author = normalize(file_meta.authors[0])

    if not norm_title or not norm_author:
        return None

    key = (norm_title, norm_author)
    candidate = candidates_by_normalized_key.get(key)
    if candidate is None:
        return None

    return MatchResult(
        method=MatchMethod.NORMALIZED_EXACT,
        candidate_book_id=candidate.id,
        score=100.0,
        auto_link=False,
    )


def match_filename(
    file_meta: FileMetadata,
    candidates_by_normalized_key: dict[tuple[str, str], BookCandidate],
) -> MatchResult | None:
    """
    Last-resort match: parse 'Author - Title.epub' from filename.

    Uses the file's basename, splits on ' - ', normalizes both halves,
    looks up in the same key as T11. Score: 80.0 (lower confidence than T11).

    Args:
        file_meta: File metadata including relative_path
        candidates_by_normalized_key: Dict mapping (normalized_title, normalized_author) tuples to BookCandidate objects

    Returns:
        MatchResult with score 80.0 if filename pattern matches and candidate found, None otherwise
    """
    basename = os.path.basename(file_meta.relative_path)
    match = FILENAME_PATTERN.match(basename)
    if match is None:
        return None

    parsed_author = match.group("author")
    parsed_title = match.group("title")

    norm_author = normalize(parsed_author)
    norm_title = normalize(parsed_title)

    if not norm_author or not norm_title:
        return None

    key = (norm_title, norm_author)
    candidate = candidates_by_normalized_key.get(key)
    if candidate is None:
        return None

    return MatchResult(
        method=MatchMethod.FILENAME,
        candidate_book_id=candidate.id,
        score=80.0,
        auto_link=False,
    )
