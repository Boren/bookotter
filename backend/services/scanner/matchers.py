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

T14 adds the cascade orchestrator (``cascade_match``) and the candidate prefilter
(``build_candidate_index``) that pre-buckets candidates so each per-file lookup
stays O(1) for tiers 9-11/13 and O(bucket_size) for the fuzzy tier.
"""

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz.fuzz import WRatio

from backend.services.scanner.normalize import normalize
from backend.services.scanner.types import (
    BookCandidate,
    FileMetadata,
    MatchMethod,
    MatchResult,
)

logger = logging.getLogger(__name__)

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


FUZZY_BUCKET_KEY_LEN = 3


@dataclass(frozen=True)
class CandidateIndex:
    """
    Pre-built lookup tables for the cascade matcher.

    Built once per scan run by ``build_candidate_index`` and consumed by
    ``cascade_match`` for every file. Already-linked candidates (file_path
    not None) are excluded — they cannot be re-matched.

    Attributes:
        by_hardcover_id: ``str(hardcover_id)`` → candidate (T9 lookup).
        by_isbn: cleaned ISBN (digits + uppercase X only) → candidate (T10).
        by_normalized_key: ``(norm_title, norm_first_author)`` → candidate
            (T11 + T13 share this dict).
        bucketed_for_fuzzy: first ``FUZZY_BUCKET_KEY_LEN`` chars of the
            normalized title → list of candidates that share that prefix.
            Caps fuzzy work at O(bucket_size) instead of O(N_total).
    """

    by_hardcover_id: dict[str, BookCandidate]
    by_isbn: dict[str, BookCandidate]
    by_normalized_key: dict[tuple[str, str], BookCandidate]
    bucketed_for_fuzzy: dict[str, list[BookCandidate]]


def _clean_isbn(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(("X" if c.upper() == "X" else c) for c in raw if c.isdigit() or c.upper() == "X")


def build_candidate_index(candidates: Iterable[BookCandidate]) -> CandidateIndex:
    """
    Build all lookup tables required by ``cascade_match``.

    Iterates the candidates exactly once. Skips any candidate that is already
    linked (``file_path is not None``) — such candidates cannot be re-matched.
    On key collisions for the dict-based tables (``by_hardcover_id``,
    ``by_isbn``, ``by_normalized_key``) the first candidate wins and a WARNING
    is logged. The fuzzy bucket is a list and accepts every candidate.

    Args:
        candidates: Iterable of ``BookCandidate`` from the database.

    Returns:
        A ``CandidateIndex`` with all four lookup tables populated.
    """
    by_hardcover_id: dict[str, BookCandidate] = {}
    by_isbn: dict[str, BookCandidate] = {}
    by_normalized_key: dict[tuple[str, str], BookCandidate] = {}
    bucketed_for_fuzzy: dict[str, list[BookCandidate]] = {}

    for candidate in candidates:
        if candidate.file_path is not None:
            continue

        if candidate.hardcover_id is not None:
            hc_key = str(candidate.hardcover_id)
            existing = by_hardcover_id.get(hc_key)
            if existing is not None:
                logger.warning(
                    "Duplicate hardcover_id %s in candidate index; first wins (kept book id=%d, dropped book id=%d)",
                    hc_key,
                    existing.id,
                    candidate.id,
                )
            else:
                by_hardcover_id[hc_key] = candidate

        cleaned_isbn = _clean_isbn(candidate.isbn)
        if cleaned_isbn:
            existing = by_isbn.get(cleaned_isbn)
            if existing is not None:
                logger.warning(
                    "Duplicate ISBN %s in candidate index; first wins (kept book id=%d, dropped book id=%d)",
                    cleaned_isbn,
                    existing.id,
                    candidate.id,
                )
            else:
                by_isbn[cleaned_isbn] = candidate

        norm_title = normalize(candidate.title)
        norm_author = normalize(candidate.author_name)
        if norm_title and norm_author:
            norm_key = (norm_title, norm_author)
            existing = by_normalized_key.get(norm_key)
            if existing is not None:
                logger.warning(
                    "Duplicate normalized title+author %r in candidate index; first wins "
                    "(kept book id=%d, dropped book id=%d)",
                    norm_key,
                    existing.id,
                    candidate.id,
                )
            else:
                by_normalized_key[norm_key] = candidate

        if norm_title:
            bucket_key = norm_title[:FUZZY_BUCKET_KEY_LEN]
            bucketed_for_fuzzy.setdefault(bucket_key, []).append(candidate)

    return CandidateIndex(
        by_hardcover_id=by_hardcover_id,
        by_isbn=by_isbn,
        by_normalized_key=by_normalized_key,
        bucketed_for_fuzzy=bucketed_for_fuzzy,
    )


def cascade_match(file_meta: FileMetadata, index: CandidateIndex) -> MatchResult | None:
    """
    Run the 5-tier matcher cascade against ``index`` and return the first hit.

    Tier order is FIXED (priority-decision; not configurable):

    1. ``match_embedded_hardcover_id`` — only auto-link tier (T9)
    2. ``match_normalized_exact`` — exact normalized title+author (T11)
    3. ``match_isbn`` — exact ISBN (T10)
    4. ``match_fuzzy`` — fuzzy title+author against the title-prefix bucket (T12)
    5. ``match_filename`` — last-resort filename parse (T13)

    The first non-None result wins; subsequent tiers are NOT invoked. Returns
    ``None`` if no tier matches. The fuzzy tier is restricted to candidates
    sharing the first ``FUZZY_BUCKET_KEY_LEN`` characters of the file's
    normalized title; if the file has no title (or the bucket is empty) the
    fuzzy tier is skipped entirely.
    """
    result = match_embedded_hardcover_id(file_meta, index.by_hardcover_id)
    if result is not None:
        return result

    result = match_normalized_exact(file_meta, index.by_normalized_key)
    if result is not None:
        return result

    result = match_isbn(file_meta, index.by_isbn)
    if result is not None:
        return result

    if file_meta.title:
        bucket_key = normalize(file_meta.title)[:FUZZY_BUCKET_KEY_LEN]
        if bucket_key:
            bucket = index.bucketed_for_fuzzy.get(bucket_key, [])
            if bucket:
                result = match_fuzzy(file_meta, bucket)
                if result is not None:
                    return result

    return match_filename(file_meta, index.by_normalized_key)
