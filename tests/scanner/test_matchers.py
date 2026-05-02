"""Unit tests for library scanner matchers (T9, T10, T11, T12, T13) and the T14 cascade."""

import logging
import time

from backend.services.scanner.matchers import (
    EMBEDDED_HARDCOVER_URN_RE,
    FILENAME_PATTERN,
    FUZZY_BUCKET_KEY_LEN,
    FUZZY_THRESHOLD,
    CandidateIndex,
    build_candidate_index,
    cascade_match,
    compute_fuzzy_score,
    match_embedded_hardcover_id,
    match_filename,
    match_fuzzy,
    match_isbn,
    match_normalized_exact,
)
from backend.services.scanner.types import BookCandidate, FileMetadata, MatchMethod


class TestIsbnMatcher:
    """Tests for ISBN matcher (T10)."""

    def test_returns_none_when_file_has_no_isbn(self):
        """ISBN matcher returns None if file has no ISBN."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidates = {}
        result = match_isbn(file_meta, candidates)
        assert result is None

    def test_returns_none_when_no_candidate_matches(self):
        """ISBN matcher returns None if no candidate ISBN matches."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="978-0-553-29335-0",
            series=None,
            series_position=None,
        )
        candidates = {
            "9780553293349": BookCandidate(
                id=1,
                hardcover_id=None,
                isbn="978-0-553-29334-9",
                title="Different Book",
                author_name="Author",
                file_path=None,
            )
        }
        result = match_isbn(file_meta, candidates)
        assert result is None

    def test_strips_hyphens_before_lookup(self):
        """ISBN matcher strips hyphens from ISBN before lookup."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="978-0-553-29335-0",
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn="978-0-553-29335-0",
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {"9780553293350": candidate}
        result = match_isbn(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1
        assert result.score == 100.0

    def test_strips_spaces_before_lookup(self):
        """ISBN matcher strips spaces from ISBN before lookup."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="978 0 553 29335 0",
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=2,
            hardcover_id=None,
            isbn="978 0 553 29335 0",
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {"9780553293350": candidate}
        result = match_isbn(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 2

    def test_score_is_100_auto_link_false(self):
        """ISBN matcher returns score 100.0 and auto_link False."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="978-0-553-29335-0",
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn="978-0-553-29335-0",
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {"9780553293350": candidate}
        result = match_isbn(file_meta, candidates)
        assert result.score == 100.0
        assert result.auto_link is False

    def test_method_is_isbn(self):
        """ISBN matcher returns MatchMethod.ISBN."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="978-0-553-29335-0",
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn="978-0-553-29335-0",
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {"9780553293350": candidate}
        result = match_isbn(file_meta, candidates)
        assert result.method == MatchMethod.ISBN

    def test_isbn_x_check_digit_handled(self):
        """ISBN matcher handles X check digit (ISBN-10)."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn="0-306-40615-X",
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn="0-306-40615-X",
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {"030640615X": candidate}
        result = match_isbn(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1


class TestNormalizedExactMatcher:
    """Tests for NormalizedExactMatcher (T11)."""

    def test_returns_none_when_title_missing(self):
        """Normalized exact matcher returns None if title is missing."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title=None,
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidates = {}
        result = match_normalized_exact(file_meta, candidates)
        assert result is None

    def test_returns_none_when_no_authors(self):
        """Normalized exact matcher returns None if no authors."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidates = {}
        result = match_normalized_exact(file_meta, candidates)
        assert result is None

    def test_returns_none_when_no_match(self):
        """Normalized exact matcher returns None if no candidate matches."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidates = {
            ("different book", "different author"): BookCandidate(
                id=1,
                hardcover_id=None,
                isbn=None,
                title="Different Book",
                author_name="Different Author",
                file_path=None,
            )
        }
        result = match_normalized_exact(file_meta, candidates)
        assert result is None

    def test_diacritics_normalized_in_lookup(self):
        """Normalized exact matcher normalizes diacritics."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Café Society",
            authors=("Müller",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Cafe Society",
            author_name="Muller",
            file_path=None,
        )
        candidates = {("cafe society", "muller"): candidate}
        result = match_normalized_exact(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1

    def test_leading_article_stripped(self):
        """Normalized exact matcher strips leading articles."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="The Foundation",
            authors=("Asimov",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Foundation",
            author_name="Asimov",
            file_path=None,
        )
        candidates = {("foundation", "asimov"): candidate}
        result = match_normalized_exact(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1

    def test_score_is_100_auto_link_false(self):
        """Normalized exact matcher returns score 100.0 and auto_link False."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {("test book", "author"): candidate}
        result = match_normalized_exact(file_meta, candidates)
        assert result.score == 100.0
        assert result.auto_link is False

    def test_method_is_normalized_exact(self):
        """Normalized exact matcher returns MatchMethod.NORMALIZED_EXACT."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author",
            file_path=None,
        )
        candidates = {("test book", "author"): candidate}
        result = match_normalized_exact(file_meta, candidates)
        assert result.method == MatchMethod.NORMALIZED_EXACT

    def test_only_first_author_used(self):
        """Normalized exact matcher uses only first author."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Asimov", "Pohl"),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Asimov",
            file_path=None,
        )
        candidates = {("test book", "asimov"): candidate}
        result = match_normalized_exact(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1


class TestFilenameMatcher:
    """Tests for FilenameMatcher (T13)."""

    def test_returns_none_when_filename_doesnt_match_pattern(self):
        """Filename matcher returns None if filename doesn't match pattern."""
        file_meta = FileMetadata(
            relative_path="test.epub",
            size_bytes=1000,
            title="Test Book",
            authors=("Author",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidates = {}
        result = match_filename(file_meta, candidates)
        assert result is None

    def test_parses_author_dash_title_pattern(self):
        """Filename matcher parses 'Author - Title.epub' pattern."""
        file_meta = FileMetadata(
            relative_path="Author Name - Test Book.epub",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author Name",
            file_path=None,
        )
        candidates = {("test book", "author name"): candidate}
        result = match_filename(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1

    def test_case_insensitive_extension(self):
        """Filename matcher handles case-insensitive .epub extension."""
        file_meta = FileMetadata(
            relative_path="Author Name - Test Book.EPUB",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author Name",
            file_path=None,
        )
        candidates = {("test book", "author name"): candidate}
        result = match_filename(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1

    def test_score_is_80_auto_link_false(self):
        """Filename matcher returns score 80.0 and auto_link False."""
        file_meta = FileMetadata(
            relative_path="Author Name - Test Book.epub",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author Name",
            file_path=None,
        )
        candidates = {("test book", "author name"): candidate}
        result = match_filename(file_meta, candidates)
        assert result.score == 80.0
        assert result.auto_link is False

    def test_method_is_filename(self):
        """Filename matcher returns MatchMethod.FILENAME."""
        file_meta = FileMetadata(
            relative_path="Author Name - Test Book.epub",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author Name",
            file_path=None,
        )
        candidates = {("test book", "author name"): candidate}
        result = match_filename(file_meta, candidates)
        assert result.method == MatchMethod.FILENAME

    def test_handles_path_with_directories(self):
        """Filename matcher extracts basename from full path."""
        file_meta = FileMetadata(
            relative_path="subdir/nested/Author Name - Test Book.epub",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Test Book",
            author_name="Author Name",
            file_path=None,
        )
        candidates = {("test book", "author name"): candidate}
        result = match_filename(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1

    def test_diacritics_in_filename_normalized(self):
        """Filename matcher normalizes diacritics in parsed author/title."""
        file_meta = FileMetadata(
            relative_path="Müller - Café Society.epub",
            size_bytes=1000,
            title=None,
            authors=(),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        candidate = BookCandidate(
            id=1,
            hardcover_id=None,
            isbn=None,
            title="Cafe Society",
            author_name="Muller",
            file_path=None,
        )
        candidates = {("cafe society", "muller"): candidate}
        result = match_filename(file_meta, candidates)
        assert result is not None
        assert result.candidate_book_id == 1


class TestFilenamePattern:
    """Tests for FILENAME_PATTERN regex."""

    def test_pattern_matches_basic_format(self):
        """FILENAME_PATTERN matches 'Author - Title.epub'."""
        match = FILENAME_PATTERN.match("Author Name - Test Book.epub")
        assert match is not None
        assert match.group("author") == "Author Name"
        assert match.group("title") == "Test Book"

    def test_pattern_case_insensitive(self):
        """FILENAME_PATTERN is case-insensitive for extension."""
        match = FILENAME_PATTERN.match("Author Name - Test Book.EPUB")
        assert match is not None

    def test_pattern_handles_multiple_spaces_around_dash(self):
        """FILENAME_PATTERN handles spaces around dash."""
        match = FILENAME_PATTERN.match("Author Name  -  Test Book.epub")
        assert match is not None
        assert match.group("author") == "Author Name"
        assert match.group("title") == "Test Book"

    def test_pattern_rejects_no_dash(self):
        """FILENAME_PATTERN rejects filenames without dash."""
        match = FILENAME_PATTERN.match("Author Name Test Book.epub")
        assert match is None

    def test_pattern_rejects_wrong_extension(self):
        """FILENAME_PATTERN rejects non-.epub extensions."""
        match = FILENAME_PATTERN.match("Author Name - Test Book.pdf")
        assert match is None


def _file_meta(
    *,
    relative_path: str = "test.epub",
    title: str | None = "Test Book",
    authors: tuple[str, ...] = ("Author",),
    identifier: str | None = None,
) -> FileMetadata:
    return FileMetadata(
        relative_path=relative_path,
        size_bytes=1000,
        title=title,
        authors=authors,
        identifier=identifier,
        isbn=None,
        series=None,
        series_position=None,
    )


def _candidate(
    *,
    cid: int = 1,
    hardcover_id: str | None = None,
    title: str = "Test Book",
    author_name: str | None = "Author",
) -> BookCandidate:
    return BookCandidate(
        id=cid,
        hardcover_id=hardcover_id,
        isbn=None,
        title=title,
        author_name=author_name,
        file_path=None,
    )


class TestEmbeddedHardcoverIdMatcher:
    """Tests for EmbeddedHardcoverIdMatcher (T9)."""

    def test_returns_none_when_identifier_is_none(self):
        result = match_embedded_hardcover_id(_file_meta(identifier=None), {"42": _candidate()})
        assert result is None

    def test_returns_none_when_regex_doesnt_match(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="978-0-553-29335-0"),
            {"42": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_uppercase(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="URN:HARDCOVER:42"),
            {"42": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_url(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="https://hardcover.app/books/42"),
            {"42": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_non_numeric(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:abc"),
            {"abc": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_partial_match(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier=" urn:hardcover:42 "),
            {"42": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_suffix(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:42-extra"),
            {"42": _candidate()},
        )
        assert result is None

    def test_strict_regex_rejects_other_urn_scheme(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:isbn:9780553293350"),
            {"9780553293350": _candidate()},
        )
        assert result is None

    def test_returns_none_when_id_not_in_candidates(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:999"),
            {"42": _candidate()},
        )
        assert result is None

    def test_successful_match_score_100_auto_link_true(self):
        candidate = _candidate(cid=7, hardcover_id="42")
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:42"),
            {"42": candidate},
        )
        assert result is not None
        assert result.candidate_book_id == 7
        assert result.score == 100.0
        assert result.auto_link is True

    def test_method_is_embedded_hardcover_id(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:42"),
            {"42": _candidate()},
        )
        assert result is not None
        assert result.method == MatchMethod.EMBEDDED_HARDCOVER_ID

    def test_single_digit_id_matches(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:1"),
            {"1": _candidate()},
        )
        assert result is not None

    def test_large_id_matches(self):
        result = match_embedded_hardcover_id(
            _file_meta(identifier="urn:hardcover:999999999"),
            {"999999999": _candidate()},
        )
        assert result is not None


class TestEmbeddedHardcoverUrnRegex:
    """Tests for EMBEDDED_HARDCOVER_URN_RE constant directly (locked by T2 spike)."""

    def test_accepts_basic_urn(self):
        match = EMBEDDED_HARDCOVER_URN_RE.match("urn:hardcover:42")
        assert match is not None
        assert match.group(1) == "42"

    def test_rejects_uppercase_scheme(self):
        assert EMBEDDED_HARDCOVER_URN_RE.match("URN:hardcover:42") is None

    def test_rejects_uppercase_namespace(self):
        assert EMBEDDED_HARDCOVER_URN_RE.match("urn:HARDCOVER:42") is None

    def test_rejects_decimal_id(self):
        assert EMBEDDED_HARDCOVER_URN_RE.match("urn:hardcover:42.5") is None

    def test_rejects_negative_id(self):
        assert EMBEDDED_HARDCOVER_URN_RE.match("urn:hardcover:-1") is None

    def test_rejects_empty_id(self):
        assert EMBEDDED_HARDCOVER_URN_RE.match("urn:hardcover:") is None


class TestFuzzyMatcher:
    """Tests for FuzzyMatcher (T12)."""

    def test_returns_none_when_no_candidates(self):
        result = match_fuzzy(_file_meta(title="Foundation", authors=("Asimov",)), [])
        assert result is None

    def test_returns_none_when_best_below_threshold(self):
        # Foundation vs I, Robot (same author) scores ~69 — known-bad pair from T8 corpus
        result = match_fuzzy(
            _file_meta(title="I, Robot", authors=("Isaac Asimov",)),
            [_candidate(title="Foundation", author_name="Isaac Asimov")],
        )
        assert result is None

    def test_returns_match_when_best_above_threshold(self):
        # Apostrophe-drop pair from T8 corpus — scores ~99
        result = match_fuzzy(
            _file_meta(title="Harry Potter and the Philosophers Stone", authors=("J.K. Rowling",)),
            [_candidate(cid=42, title="Harry Potter and the Philosopher's Stone", author_name="J.K. Rowling")],
        )
        assert result is not None
        assert result.candidate_book_id == 42
        assert result.score >= FUZZY_THRESHOLD

    def test_picks_best_score_when_multiple_above_threshold(self):
        result = match_fuzzy(
            _file_meta(title="Harry Potter and the Philosophers Stone", authors=("J.K. Rowling",)),
            [
                _candidate(cid=1, title="Harry Potter and the Philosopher Stone", author_name="J.K. Rowling"),
                _candidate(cid=2, title="Harry Potter and the Philosopher's Stone", author_name="J.K. Rowling"),
                _candidate(cid=3, title="Harry Potter and the Philosophers Stone", author_name="J.K. Rowling"),
            ],
        )
        assert result is not None
        assert result.candidate_book_id == 3

    def test_method_is_fuzzy_auto_link_false(self):
        result = match_fuzzy(
            _file_meta(title="Harry Potter and the Philosophers Stone", authors=("J.K. Rowling",)),
            [_candidate(title="Harry Potter and the Philosopher's Stone", author_name="J.K. Rowling")],
        )
        assert result is not None
        assert result.method == MatchMethod.FUZZY
        assert result.auto_link is False

    def test_handles_missing_file_author(self):
        result = match_fuzzy(
            _file_meta(title="Harry Potter and the Philosophers Stone", authors=()),
            [_candidate(title="Harry Potter and the Philosophers Stone", author_name="J.K. Rowling")],
        )
        assert result is not None

    def test_handles_missing_candidate_author(self):
        result = match_fuzzy(
            _file_meta(title="Harry Potter and the Philosophers Stone", authors=("J.K. Rowling",)),
            [_candidate(title="Harry Potter and the Philosophers Stone", author_name=None)],
        )
        assert result is not None

    def test_returns_none_when_file_has_no_title(self):
        result = match_fuzzy(
            _file_meta(title=None, authors=("Asimov",)),
            [_candidate(title="Foundation", author_name="Asimov")],
        )
        assert result is None

    def test_returns_none_when_file_title_is_empty(self):
        result = match_fuzzy(
            _file_meta(title="", authors=("Asimov",)),
            [_candidate(title="Foundation", author_name="Asimov")],
        )
        assert result is None


class TestComputeFuzzyScore:
    """Tests for compute_fuzzy_score helper (used by T8 corpus + T12 matcher)."""

    def test_identical_strings_score_100(self):
        score = compute_fuzzy_score(
            book_title="Test Book",
            book_author="Author Name",
            file_title="Test Book",
            file_author="Author Name",
        )
        assert score == 100.0

    def test_diacritic_normalized_pair_high_score(self):
        score = compute_fuzzy_score(
            book_title="Cafe Society",
            book_author="Author Name",
            file_title="Café Society",
            file_author="Author Name",
        )
        assert score == 100.0

    def test_completely_different_score_low(self):
        score = compute_fuzzy_score(
            book_title="Foundation",
            book_author="Isaac Asimov",
            file_title="Pride and Prejudice",
            file_author="Jane Austen",
        )
        assert score < FUZZY_THRESHOLD

    def test_handles_none_book_author(self):
        score = compute_fuzzy_score(
            book_title="Test Book",
            book_author=None,
            file_title="Test Book",
            file_author="",
        )
        assert score == 100.0

    def test_returns_float_in_zero_to_hundred_range(self):
        score = compute_fuzzy_score(
            book_title="A",
            book_author="B",
            file_title="C",
            file_author="D",
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0


def _candidate_full(
    *,
    cid: int = 1,
    hardcover_id: str | None = None,
    isbn: str | None = None,
    title: str = "Test Book",
    author_name: str | None = "Author",
    file_path: str | None = None,
) -> BookCandidate:
    return BookCandidate(
        id=cid,
        hardcover_id=hardcover_id,
        isbn=isbn,
        title=title,
        author_name=author_name,
        file_path=file_path,
    )


class TestBuildCandidateIndex:
    """Tests for the candidate prefilter (T14)."""

    def test_empty_input_returns_empty_index(self):
        index = build_candidate_index([])
        assert isinstance(index, CandidateIndex)
        assert index.by_hardcover_id == {}
        assert index.by_isbn == {}
        assert index.by_normalized_key == {}
        assert index.bucketed_for_fuzzy == {}

    def test_excludes_already_linked_candidates(self):
        linked = _candidate_full(
            cid=1,
            hardcover_id="42",
            isbn="9780553293350",
            title="Foundation",
            author_name="Asimov",
            file_path="/library/Asimov/Foundation.epub",
        )
        unlinked = _candidate_full(
            cid=2,
            hardcover_id="43",
            isbn="9780553293351",
            title="Dune",
            author_name="Herbert",
            file_path=None,
        )
        index = build_candidate_index([linked, unlinked])
        assert "42" not in index.by_hardcover_id
        assert "9780553293350" not in index.by_isbn
        assert ("foundation", "asimov") not in index.by_normalized_key
        assert "fou" not in index.bucketed_for_fuzzy
        assert index.by_hardcover_id["43"].id == 2
        assert index.by_isbn["9780553293351"].id == 2
        assert index.by_normalized_key[("dune", "herbert")].id == 2
        assert index.bucketed_for_fuzzy["dun"][0].id == 2

    def test_indexes_by_hardcover_id_as_string(self):
        candidate = _candidate_full(cid=1, hardcover_id="123456")
        index = build_candidate_index([candidate])
        assert "123456" in index.by_hardcover_id
        assert index.by_hardcover_id["123456"].id == 1

    def test_skips_candidates_with_no_hardcover_id(self):
        candidate = _candidate_full(cid=1, hardcover_id=None, title="Foundation", author_name="Asimov")
        index = build_candidate_index([candidate])
        assert index.by_hardcover_id == {}
        assert ("foundation", "asimov") in index.by_normalized_key

    def test_isbn_cleaned_strips_hyphens_and_spaces(self):
        candidate = _candidate_full(cid=1, isbn="978-0-553 29335 0")
        index = build_candidate_index([candidate])
        assert "9780553293350" in index.by_isbn
        assert index.by_isbn["9780553293350"].id == 1

    def test_isbn_x_check_digit_uppercased(self):
        candidate = _candidate_full(cid=1, isbn="0-306-40615-x")
        index = build_candidate_index([candidate])
        assert "030640615X" in index.by_isbn
        assert "030640615x" not in index.by_isbn

    def test_skips_candidates_with_empty_cleaned_isbn(self):
        candidate = _candidate_full(cid=1, isbn="--- ", title="Foundation", author_name="Asimov")
        index = build_candidate_index([candidate])
        assert index.by_isbn == {}
        assert ("foundation", "asimov") in index.by_normalized_key

    def test_normalized_key_uses_candidate_title_and_author(self):
        candidate = _candidate_full(cid=1, title="The Foundation", author_name="Isaac Asimov")
        index = build_candidate_index([candidate])
        assert ("foundation", "isaac asimov") in index.by_normalized_key

    def test_skips_normalized_key_when_author_is_none(self):
        candidate = _candidate_full(cid=1, title="Foundation", author_name=None)
        index = build_candidate_index([candidate])
        assert index.by_normalized_key == {}
        assert "fou" in index.bucketed_for_fuzzy

    def test_fuzzy_bucket_key_is_first_3_normalized_chars(self):
        candidate = _candidate_full(cid=1, title="The Foundation", author_name="Asimov")
        index = build_candidate_index([candidate])
        assert "fou" in index.bucketed_for_fuzzy
        assert index.bucketed_for_fuzzy["fou"] == [candidate]
        assert FUZZY_BUCKET_KEY_LEN == 3

    def test_fuzzy_bucket_groups_candidates_sharing_prefix(self):
        a = _candidate_full(cid=1, title="Foundation", author_name="Asimov")
        b = _candidate_full(cid=2, title="Foundations of Statistics", author_name="Savage")
        c = _candidate_full(cid=3, title="Dune", author_name="Herbert")
        index = build_candidate_index([a, b, c])
        assert {cand.id for cand in index.bucketed_for_fuzzy["fou"]} == {1, 2}
        assert [cand.id for cand in index.bucketed_for_fuzzy["dun"]] == [3]

    def test_fuzzy_bucket_skips_candidates_with_empty_normalized_title(self):
        candidate = _candidate_full(cid=1, title="   ", author_name="Asimov")
        index = build_candidate_index([candidate])
        assert index.bucketed_for_fuzzy == {}

    def test_collision_first_wins_with_warning(self, caplog):
        first = _candidate_full(cid=1, hardcover_id="42", title="Foundation", author_name="Asimov")
        second = _candidate_full(cid=2, hardcover_id="42", title="Different Book", author_name="Other")
        with caplog.at_level(logging.WARNING):
            index = build_candidate_index([first, second])
        assert index.by_hardcover_id["42"].id == 1
        warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
        assert any("42" in rec.getMessage() for rec in warnings)

    def test_isbn_collision_first_wins_with_warning(self, caplog):
        first = _candidate_full(cid=1, isbn="9780553293350", title="A", author_name="X")
        second = _candidate_full(cid=2, isbn="978-0-553-29335-0", title="B", author_name="Y")
        with caplog.at_level(logging.WARNING):
            index = build_candidate_index([first, second])
        assert index.by_isbn["9780553293350"].id == 1
        assert any("9780553293350" in rec.getMessage() for rec in caplog.records)

    def test_normalized_key_collision_first_wins_with_warning(self, caplog):
        first = _candidate_full(cid=1, title="Foundation", author_name="Asimov")
        second = _candidate_full(cid=2, title="THE Foundation", author_name="Asimov")
        with caplog.at_level(logging.WARNING):
            index = build_candidate_index([first, second])
        assert index.by_normalized_key[("foundation", "asimov")].id == 1
        assert any("foundation" in rec.getMessage() for rec in caplog.records)

    def test_fuzzy_bucket_keeps_all_candidates_no_collision(self):
        a = _candidate_full(cid=1, title="Foundation", author_name="Asimov")
        b = _candidate_full(cid=2, title="Foundation", author_name="Asimov")
        index = build_candidate_index([a, b])
        assert len(index.bucketed_for_fuzzy["fou"]) == 2


def _meta(
    *,
    relative_path: str = "test.epub",
    title: str | None = None,
    authors: tuple[str, ...] = (),
    identifier: str | None = None,
    isbn: str | None = None,
) -> FileMetadata:
    return FileMetadata(
        relative_path=relative_path,
        size_bytes=1000,
        title=title,
        authors=authors,
        identifier=identifier,
        isbn=isbn,
        series=None,
        series_position=None,
    )


class TestCascade:
    """Tests for the cascade orchestrator (T14)."""

    def test_returns_none_when_no_tier_matches(self):
        index = build_candidate_index(
            [_candidate_full(cid=1, hardcover_id="42", title="Foundation", author_name="Asimov")],
        )
        result = cascade_match(_meta(relative_path="random_unparseable_file.epub"), index)
        assert result is None

    def test_embedded_id_wins_over_other_tiers(self):
        embedded_target = _candidate_full(cid=1, hardcover_id="42", title="EmbeddedTitle", author_name="EmbeddedAuth")
        normalized_target = _candidate_full(cid=2, title="Foo", author_name="Bar")
        isbn_target = _candidate_full(cid=3, isbn="9780553293350")
        index = build_candidate_index([embedded_target, normalized_target, isbn_target])
        result = cascade_match(
            _meta(
                identifier="urn:hardcover:42",
                title="Foo",
                authors=("Bar",),
                isbn="978-0-553-29335-0",
                relative_path="Bar - Foo.epub",
            ),
            index,
        )
        assert result is not None
        assert result.method == MatchMethod.EMBEDDED_HARDCOVER_ID
        assert result.candidate_book_id == 1
        assert result.auto_link is True

    def test_normalized_exact_wins_over_isbn(self):
        normalized_target = _candidate_full(cid=2, title="Foo", author_name="Bar")
        isbn_target = _candidate_full(cid=3, isbn="9780553293350", title="Different", author_name="Other")
        index = build_candidate_index([normalized_target, isbn_target])
        result = cascade_match(
            _meta(title="Foo", authors=("Bar",), isbn="978-0-553-29335-0"),
            index,
        )
        assert result is not None
        assert result.method == MatchMethod.NORMALIZED_EXACT
        assert result.candidate_book_id == 2

    def test_isbn_wins_over_fuzzy(self):
        isbn_target = _candidate_full(cid=3, isbn="9780553293350", title="UnrelatedXyz", author_name="Nobody")
        fuzzy_target = _candidate_full(cid=4, title="Foundationn", author_name="Asimovv")
        index = build_candidate_index([isbn_target, fuzzy_target])
        result = cascade_match(
            _meta(title="Foundation", authors=("Asimov",), isbn="978-0-553-29335-0"),
            index,
        )
        assert result is not None
        assert result.method == MatchMethod.ISBN
        assert result.candidate_book_id == 3

    def test_fuzzy_wins_over_filename(self):
        fuzzy_target = _candidate_full(cid=5, title="Foundation", author_name="Asimov")
        filename_target = _candidate_full(cid=6, title="DifferentBook", author_name="OtherAuthor")
        index = build_candidate_index([fuzzy_target, filename_target])
        result = cascade_match(
            _meta(
                title="Foundationn",
                authors=("Asimovv",),
                relative_path="OtherAuthor - DifferentBook.epub",
            ),
            index,
        )
        assert result is not None
        assert result.method == MatchMethod.FUZZY
        assert result.candidate_book_id == 5

    def test_filename_used_only_when_others_fail(self):
        target = _candidate_full(cid=7, title="Foundation", author_name="Asimov")
        index = build_candidate_index([target])
        result = cascade_match(
            _meta(relative_path="Asimov - Foundation.epub"),
            index,
        )
        assert result is not None
        assert result.method == MatchMethod.FILENAME
        assert result.candidate_book_id == 7

    def test_first_hit_wins_subsequent_tiers_not_called(self, monkeypatch):
        calls: list[str] = []

        def make_tracker(name: str):
            def tracker(*_args, **_kwargs):
                calls.append(name)
                return None

            return tracker

        monkeypatch.setattr(
            "backend.services.scanner.matchers.match_normalized_exact",
            make_tracker("normalized_exact"),
        )
        monkeypatch.setattr("backend.services.scanner.matchers.match_isbn", make_tracker("isbn"))
        monkeypatch.setattr("backend.services.scanner.matchers.match_fuzzy", make_tracker("fuzzy"))
        monkeypatch.setattr("backend.services.scanner.matchers.match_filename", make_tracker("filename"))

        embedded_target = _candidate_full(cid=1, hardcover_id="42")
        index = build_candidate_index([embedded_target])
        result = cascade_match(_meta(identifier="urn:hardcover:42"), index)

        assert result is not None
        assert result.method == MatchMethod.EMBEDDED_HARDCOVER_ID
        assert calls == []

    def test_auto_link_true_only_for_embedded(self):
        embedded = _candidate_full(cid=10, hardcover_id="100", title="EmbeddedTitle", author_name="EmbeddedAuth")
        normalized = _candidate_full(cid=11, title="NormalizedFoo", author_name="NormalizedBar")
        isbn_only = _candidate_full(cid=12, isbn="9780000000001", title="IsbnTitle", author_name="IsbnAuthor")
        fuzzy_only = _candidate_full(cid=13, title="FuzzyFoundation", author_name="FuzzyAsimov")
        filename_only = _candidate_full(cid=14, title="FilenameTitle", author_name="FilenameAuthor")
        index = build_candidate_index([embedded, normalized, isbn_only, fuzzy_only, filename_only])

        embedded_result = cascade_match(_meta(identifier="urn:hardcover:100"), index)
        assert embedded_result is not None
        assert embedded_result.auto_link is True

        normalized_result = cascade_match(_meta(title="NormalizedFoo", authors=("NormalizedBar",)), index)
        assert normalized_result is not None
        assert normalized_result.method == MatchMethod.NORMALIZED_EXACT
        assert normalized_result.auto_link is False

        isbn_result = cascade_match(_meta(isbn="9780000000001"), index)
        assert isbn_result is not None
        assert isbn_result.method == MatchMethod.ISBN
        assert isbn_result.auto_link is False

        fuzzy_result = cascade_match(_meta(title="FuzzyFoundationn", authors=("FuzzyAsimovv",)), index)
        assert fuzzy_result is not None
        assert fuzzy_result.method == MatchMethod.FUZZY
        assert fuzzy_result.auto_link is False

        filename_result = cascade_match(
            _meta(relative_path="FilenameAuthor - FilenameTitle.epub"),
            index,
        )
        assert filename_result is not None
        assert filename_result.method == MatchMethod.FILENAME
        assert filename_result.auto_link is False

    def test_skips_fuzzy_when_file_has_no_title(self):
        target = _candidate_full(cid=1, title="Foundation", author_name="Asimov")
        index = build_candidate_index([target])
        result = cascade_match(_meta(title=None), index)
        assert result is None

    def test_skips_fuzzy_when_bucket_empty(self):
        target = _candidate_full(cid=1, title="Dune", author_name="Herbert")
        index = build_candidate_index([target])
        result = cascade_match(_meta(title="Foundation", authors=("Asimov",)), index)
        assert result is None


class TestCascadePerformance:
    """Big-O sanity check for the cascade prefilter (T14)."""

    @staticmethod
    def _build_perf_candidates(n: int) -> list[BookCandidate]:
        title_seeds = [
            "Foundation",
            "Dune",
            "Hyperion",
            "Neuromancer",
            "Snow Crash",
            "Cryptonomicon",
            "Anathem",
            "Ender",
            "Speaker",
            "Children",
            "Pattern",
            "Cantos",
            "Stranger",
            "Gateway",
            "Rendezvous",
            "Childhood",
            "Diamond",
            "Quicksilver",
            "Confusion",
            "Reamde",
        ]
        author_seeds = [
            "Asimov",
            "Herbert",
            "Simmons",
            "Gibson",
            "Stephenson",
            "Card",
            "Heinlein",
            "Clarke",
            "Pohl",
            "Le Guin",
        ]
        candidates: list[BookCandidate] = []
        for idx in range(n):
            title = f"{title_seeds[idx % len(title_seeds)]} Volume {idx}"
            author = f"{author_seeds[idx % len(author_seeds)]} {idx // len(author_seeds)}"
            candidates.append(
                BookCandidate(
                    id=idx + 1,
                    hardcover_id=str(1_000_000 + idx),
                    isbn=f"978{idx:010d}",
                    title=title,
                    author_name=author,
                    file_path=None,
                )
            )
        return candidates

    @staticmethod
    def _build_perf_files(candidates: list[BookCandidate], n_files: int) -> list[FileMetadata]:
        files: list[FileMetadata] = []
        for i in range(n_files):
            tier = i % 5
            if tier == 0:
                target = candidates[i % len(candidates)]
                files.append(_meta(identifier=f"urn:hardcover:{target.hardcover_id}"))
            elif tier == 1:
                target = candidates[i % len(candidates)]
                assert target.author_name is not None
                files.append(_meta(title=target.title, authors=(target.author_name,)))
            elif tier == 2:
                target = candidates[i % len(candidates)]
                assert target.isbn is not None
                files.append(_meta(isbn=target.isbn))
            elif tier == 3:
                target = candidates[i % len(candidates)]
                assert target.author_name is not None
                files.append(
                    _meta(
                        title=target.title + "x",
                        authors=(target.author_name + "y",),
                    )
                )
            else:
                files.append(
                    _meta(
                        title="Completely Unrelated Title XYZ",
                        authors=("Nobody Important",),
                        relative_path="random_no_dash.epub",
                    )
                )
        return files

    def test_1000_book_library_completes_in_reasonable_time(self):
        candidates = self._build_perf_candidates(1000)
        files = self._build_perf_files(candidates, 100)

        start = time.perf_counter()
        index = build_candidate_index(candidates)
        results = [cascade_match(file_meta, index) for file_meta in files]
        elapsed = time.perf_counter() - start

        budget_seconds = 0.5
        assert elapsed < budget_seconds, (
            f"Cascade over 1000 candidates × 100 files took {elapsed:.3f}s (budget {budget_seconds}s) — "
            "prefilter regression suspected"
        )
        assert len(results) == 100
        non_none = [r for r in results if r is not None]
        assert len(non_none) >= 60
