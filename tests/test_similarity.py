"""Tests for backend.utils.similarity."""

from backend.utils.similarity import (
    author_surname_match,
    normalize_for_match,
    parse_release_title,
    title_similarity,
)


class TestNormalizeForMatch:
    def test_diacritic_insensitive(self):
        assert normalize_for_match("Café") == normalize_for_match("Cafe")

    def test_lowercase(self):
        assert normalize_for_match("HELLO") == "hello"

    def test_punctuation_stripped(self):
        result = normalize_for_match("Hello, World!")
        assert "," not in result
        assert "!" not in result


class TestTitleSimilarity:
    def test_identical_strings(self):
        assert title_similarity("Dune", "Dune") == 1.0

    def test_partial_match_high(self):
        score = title_similarity("Dune", "Dune: Special Edition")
        assert score >= 0.3, f"Expected >= 0.3, got {score}"

    def test_completely_different(self):
        score = title_similarity("Foundation", "Pride and Prejudice")
        assert score < 0.3, f"Expected < 0.3, got {score}"

    def test_diacritic_insensitive(self):
        score = title_similarity("Café Society", "Cafe Society")
        assert score == 1.0, f"Expected 1.0, got {score}"

    def test_empty_strings(self):
        assert title_similarity("", "") == 1.0
        assert title_similarity("foo", "") == 0.0


class TestAuthorSurnameMatch:
    def test_matching_surnames_standard(self):
        assert author_surname_match(["Frank Herbert"], ["Herbert, Frank"]) is True

    def test_non_matching_surnames(self):
        assert author_surname_match(["Asimov"], ["Herbert"]) is False

    def test_case_insensitive(self):
        assert author_surname_match(["TOLKIEN"], ["tolkien"]) is True

    def test_multiple_authors_any_match(self):
        assert author_surname_match(["Frank Herbert", "Isaac Asimov"], ["Herbert, Frank"]) is True

    def test_empty_lists(self):
        assert author_surname_match([], ["Herbert"]) is False
        assert author_surname_match(["Herbert"], []) is False


class TestParseReleaseTitle:
    def test_splits_title_author_and_strips_tags(self):
        title, author = parse_release_title("The Name of the Wind by Patrick Rothfuss [ENG / EPUB]")
        assert title == "The Name of the Wind"
        assert author == "Patrick Rothfuss"

    def test_uses_last_by_separator(self):
        title, author = parse_release_title("Death by Water by Kenzaburo Oe")
        assert title == "Death by Water"
        assert author == "Kenzaburo Oe"

    def test_no_author_part_returns_empty_author(self):
        title, author = parse_release_title("Standalone Title [EPUB]")
        assert title == "Standalone Title"
        assert author == ""

    def test_parenthesized_tags_stripped(self):
        title, author = parse_release_title("Dune by Frank Herbert (retail) (epub)")
        assert title == "Dune"
        assert author == "Frank Herbert"
