"""Unit tests for library scanner matchers (T10, T11, T13)."""


from backend.services.scanner.matchers import (
    FILENAME_PATTERN,
    match_filename,
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
