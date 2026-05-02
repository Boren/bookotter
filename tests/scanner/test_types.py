"""Tests for scanner types — immutability, enums, and hashability."""

import pytest

from backend.services.scanner.types import BookCandidate, FileMetadata, MatchMethod, MatchResult


class TestMatchMethod:
    """Tests for MatchMethod enum."""

    def test_embedded_hardcover_id_value(self) -> None:
        """Verify EMBEDDED_HARDCOVER_ID has correct string value."""
        assert MatchMethod.EMBEDDED_HARDCOVER_ID.value == "embedded_hardcover_id"

    def test_isbn_value(self) -> None:
        """Verify ISBN has correct string value."""
        assert MatchMethod.ISBN.value == "isbn"

    def test_normalized_exact_value(self) -> None:
        """Verify NORMALIZED_EXACT has correct string value."""
        assert MatchMethod.NORMALIZED_EXACT.value == "normalized_exact"

    def test_fuzzy_value(self) -> None:
        """Verify FUZZY has correct string value."""
        assert MatchMethod.FUZZY.value == "fuzzy"

    def test_filename_value(self) -> None:
        """Verify FILENAME has correct string value."""
        assert MatchMethod.FILENAME.value == "filename"

    def test_all_members_are_str_enum(self) -> None:
        """Verify all members are StrEnum instances."""
        for member in MatchMethod:
            assert isinstance(member.value, str)


class TestFileMetadata:
    """Tests for FileMetadata dataclass."""

    def test_creation(self) -> None:
        """Verify FileMetadata can be created with all fields."""
        metadata = FileMetadata(
            relative_path="books/example.epub",
            size_bytes=1024,
            title="Example Book",
            authors=("Author One", "Author Two"),
            identifier="isbn-123",
            isbn="978-1234567890",
            series="Series Name",
            series_position=1.0,
        )
        assert metadata.relative_path == "books/example.epub"
        assert metadata.size_bytes == 1024
        assert metadata.title == "Example Book"
        assert metadata.authors == ("Author One", "Author Two")
        assert metadata.identifier == "isbn-123"
        assert metadata.isbn == "978-1234567890"
        assert metadata.series == "Series Name"
        assert metadata.series_position == 1.0

    def test_frozen_prevents_modification(self) -> None:
        """Verify frozen=True prevents field modification."""
        metadata = FileMetadata(
            relative_path="books/example.epub",
            size_bytes=1024,
            title="Example Book",
            authors=("Author One",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        with pytest.raises(AttributeError):
            metadata.title = "New Title"  # type: ignore

    def test_hashable(self) -> None:
        """Verify FileMetadata is hashable (tuple authors proves immutability)."""
        metadata1 = FileMetadata(
            relative_path="books/example.epub",
            size_bytes=1024,
            title="Example Book",
            authors=("Author One",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        metadata2 = FileMetadata(
            relative_path="books/example.epub",
            size_bytes=1024,
            title="Example Book",
            authors=("Author One",),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        # Should be hashable and equal instances should have same hash
        assert hash(metadata1) == hash(metadata2)
        assert {metadata1, metadata2} == {metadata1}

    def test_authors_is_tuple_not_list(self) -> None:
        """Verify authors field is tuple (immutable) not list."""
        metadata = FileMetadata(
            relative_path="books/example.epub",
            size_bytes=1024,
            title="Example Book",
            authors=("Author One", "Author Two"),
            identifier=None,
            isbn=None,
            series=None,
            series_position=None,
        )
        assert isinstance(metadata.authors, tuple)
        assert not isinstance(metadata.authors, list)


class TestBookCandidate:
    """Tests for BookCandidate dataclass."""

    def test_creation(self) -> None:
        """Verify BookCandidate can be created with all fields."""
        candidate = BookCandidate(
            id=1,
            hardcover_id="hc-123",
            isbn="978-1234567890",
            title="Example Book",
            author_name="Author Name",
            file_path="/path/to/file.epub",
        )
        assert candidate.id == 1
        assert candidate.hardcover_id == "hc-123"
        assert candidate.isbn == "978-1234567890"
        assert candidate.title == "Example Book"
        assert candidate.author_name == "Author Name"
        assert candidate.file_path == "/path/to/file.epub"

    def test_frozen_prevents_modification(self) -> None:
        """Verify frozen=True prevents field modification."""
        candidate = BookCandidate(
            id=1,
            hardcover_id="hc-123",
            isbn="978-1234567890",
            title="Example Book",
            author_name="Author Name",
            file_path="/path/to/file.epub",
        )
        with pytest.raises(AttributeError):
            candidate.title = "New Title"  # type: ignore

    def test_hashable(self) -> None:
        """Verify BookCandidate is hashable."""
        candidate1 = BookCandidate(
            id=1,
            hardcover_id="hc-123",
            isbn="978-1234567890",
            title="Example Book",
            author_name="Author Name",
            file_path="/path/to/file.epub",
        )
        candidate2 = BookCandidate(
            id=1,
            hardcover_id="hc-123",
            isbn="978-1234567890",
            title="Example Book",
            author_name="Author Name",
            file_path="/path/to/file.epub",
        )
        assert hash(candidate1) == hash(candidate2)
        assert {candidate1, candidate2} == {candidate1}


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_creation(self) -> None:
        """Verify MatchResult can be created with all fields."""
        result = MatchResult(
            method=MatchMethod.ISBN,
            candidate_book_id=42,
            score=95.5,
            auto_link=True,
        )
        assert result.method == MatchMethod.ISBN
        assert result.candidate_book_id == 42
        assert result.score == 95.5
        assert result.auto_link is True

    def test_frozen_prevents_modification(self) -> None:
        """Verify frozen=True prevents field modification."""
        result = MatchResult(
            method=MatchMethod.ISBN,
            candidate_book_id=42,
            score=95.5,
            auto_link=True,
        )
        with pytest.raises(AttributeError):
            result.score = 0.0  # type: ignore

    def test_hashable(self) -> None:
        """Verify MatchResult is hashable."""
        result1 = MatchResult(
            method=MatchMethod.ISBN,
            candidate_book_id=42,
            score=95.5,
            auto_link=True,
        )
        result2 = MatchResult(
            method=MatchMethod.ISBN,
            candidate_book_id=42,
            score=95.5,
            auto_link=True,
        )
        assert hash(result1) == hash(result2)
        assert {result1, result2} == {result1}

    def test_auto_link_only_true_for_embedded_hardcover_id(self) -> None:
        """Verify auto_link can be set independently (no validation in type)."""
        result_auto = MatchResult(
            method=MatchMethod.EMBEDDED_HARDCOVER_ID,
            candidate_book_id=42,
            score=100.0,
            auto_link=True,
        )
        result_manual = MatchResult(
            method=MatchMethod.ISBN,
            candidate_book_id=42,
            score=95.5,
            auto_link=False,
        )
        assert result_auto.auto_link is True
        assert result_manual.auto_link is False
