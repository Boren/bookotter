"""
Pure-function matcher tiers for library scanner cascade.

Implements all five matching tiers:
- T9:  EmbeddedHardcoverIdMatcher (auto-link tier; strict urn:hardcover:<id> regex)
- T10: ISBN matcher (exact match post-hyphen-strip)
- T11: NormalizedExactMatcher (exact match on normalized title + first author)
- T12: FuzzyMatcher (rapidfuzz WRatio with corpus-validated threshold)
- T13: FilenameMatcher (last-resort: parse 'Author - Title.epub' from filename)

All matchers follow the same shape: take a FileMetadata plus a candidate index
(or list, for fuzzy), and return MatchResult or None.
"""

import os
import re

from rapidfuzz.fuzz import WRatio

from backend.services.scanner.normalize import normalize
from backend.services.scanner.types import (
    BookCandidate,
    FileMetadata,
    MatchMethod,
    MatchResult,
)

# Filename pattern: "Author - Title.epub" (last-resort tier)
FILENAME_PATTERN = re.compile(r"^(?P<author>.+?)\s*-\s*(?P<title>.+?)\.epub$", re.IGNORECASE)

# T9: Embedded Hardcover URN — strict, anchored, lowercase scheme, numeric ID only.
# Locked by .sisyphus/evidence/task-2-urn-format.md (T2 spike).
EMBEDDED_HARDCOVER_URN_RE = re.compile(r"^urn:hardcover:(\d+)$")

# T12: Fuzzy match threshold — locked by tests/scanner/fixtures/fuzzy_pairs.json (T8 corpus).
# Observed corpus separation: min(should_match)=85.50, max(should_not_match)=79.41 (delta=6.09).
FUZZY_THRESHOLD = 85.0


def match_embedded_hardcover_id(
    file_meta: FileMetadata,
    candidates_by_hardcover_id: dict[str, BookCandidate],
) -> MatchResult | None:
    """
    Match by embedded Hardcover URN in EPUB DC:identifier.

    Uses the strict regex ``^urn:hardcover:(\\d+)$``. Any deviation
    (uppercase, surrounding whitespace, non-numeric ID, URLs, ISBN-formatted
    strings, etc.) fails. This is the only auto-link tier — score 100.0 with
    ``auto_link=True``.

    Args:
        file_meta: File metadata; ``identifier`` carries the candidate URN.
        candidates_by_hardcover_id: Dict mapping ``str(hardcover_id)`` to BookCandidate.
            Caller is responsible for keying by string IDs to match the regex capture.

    Returns:
        MatchResult with score 100.0 and auto_link=True if the URN matches and
        the extracted hardcover_id is present in the candidate dict; None otherwise.
    """
    if file_meta.identifier is None:
        return None

    match = EMBEDDED_HARDCOVER_URN_RE.match(file_meta.identifier)
    if match is None:
        return None

    hardcover_id = match.group(1)
    candidate = candidates_by_hardcover_id.get(hardcover_id)
    if candidate is None:
        return None

    return MatchResult(
        method=MatchMethod.EMBEDDED_HARDCOVER_ID,
        candidate_book_id=candidate.id,
        score=100.0,
        auto_link=True,
    )


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


def compute_fuzzy_score(
    *,
    book_title: str,
    book_author: str | None,
    file_title: str,
    file_author: str,
) -> float:
    """
    Compute the fuzzy similarity score for a (book, file) pair.

    Builds the canonical query string ``normalize(f"{title} {author}")`` for
    both sides and runs ``rapidfuzz.fuzz.WRatio`` against them. Used by the
    T8 corpus test and by ``match_fuzzy``.

    Args:
        book_title: Candidate book title.
        book_author: Candidate book author (None is treated as empty).
        file_title: File-extracted title.
        file_author: File-extracted author.

    Returns:
        WRatio score in [0.0, 100.0].
    """
    book_query = normalize(f"{book_title} {book_author or ''}")
    file_query = normalize(f"{file_title} {file_author}")
    return WRatio(file_query, book_query)


def match_fuzzy(
    file_meta: FileMetadata,
    candidates: list[BookCandidate],
) -> MatchResult | None:
    """
    Match by fuzzy title+author similarity (rapidfuzz WRatio).

    Computes ``compute_fuzzy_score`` against every candidate and keeps the
    highest. Returns a MatchResult only when the best score meets
    ``FUZZY_THRESHOLD`` (locked by the T8 corpus). Never auto-links — fuzzy
    matches always require human confirmation.

    Args:
        file_meta: File metadata including title and (optional) authors.
        candidates: List of BookCandidate objects to score against. Caller is
            expected to pre-filter (e.g., via the T14 cascade) so this list
            stays small.

    Returns:
        MatchResult with the WRatio score and ``auto_link=False`` if the best
        candidate scores at or above ``FUZZY_THRESHOLD``; None otherwise.
    """
    if not candidates:
        return None

    if not file_meta.title:
        return None

    file_author = file_meta.authors[0] if file_meta.authors else ""

    best_score = -1.0
    best_candidate: BookCandidate | None = None
    for candidate in candidates:
        score = compute_fuzzy_score(
            book_title=candidate.title,
            book_author=candidate.author_name,
            file_title=file_meta.title,
            file_author=file_author,
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None or best_score < FUZZY_THRESHOLD:
        return None

    return MatchResult(
        method=MatchMethod.FUZZY,
        candidate_book_id=best_candidate.id,
        score=best_score,
        auto_link=False,
    )
