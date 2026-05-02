"""Unit tests for library scanner matchers (T9, T10, T11, T12, T13)."""

from backend.services.scanner.matchers import (
    EMBEDDED_HARDCOVER_URN_RE,
    FILENAME_PATTERN,
    FUZZY_THRESHOLD,
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
