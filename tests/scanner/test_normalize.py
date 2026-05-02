"""
Comprehensive tests for the string normalizer module.

Tests cover:
- Empty and None inputs
- ASCII text
- Diacritics (French, German, Spanish)
- Full-width Unicode characters
- Leading articles (the, a, an)
- Non-leading articles preservation
- Whitespace collapsing
- Idempotence
- Mixed case
"""

from backend.services.scanner.normalize import normalize


class TestNormalizeBasics:
    """Test basic functionality."""

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert normalize("") == ""

    def test_none_input(self):
        """None input returns empty string."""
        assert normalize(None) == ""

    def test_plain_ascii(self):
        """Plain ASCII text is lowercased."""
        assert normalize("Hello World") == "hello world"

    def test_mixed_case(self):
        """Mixed case is normalized to lowercase."""
        assert normalize("ThE QuIcK BrOwN FoX") == "quick brown fox"  # "the " is stripped


class TestNormalizeDiacritics:
    """Test diacritic stripping."""

    def test_french_diacritics(self):
        """French accents are stripped."""
        assert normalize("Café") == "cafe"
        assert normalize("Résumé") == "resume"
        assert normalize("Naïve") == "naive"

    def test_german_diacritics(self):
        """German umlauts are stripped."""
        assert normalize("Müller") == "muller"
        assert normalize("Schöne") == "schone"
        assert normalize("Größe") == "große"  # ö → o (combining mark stripped), ß unchanged

    def test_spanish_diacritics(self):
        """Spanish accents are stripped."""
        assert normalize("Español") == "espanol"
        assert normalize("Niño") == "nino"


class TestNormalizeFullWidth:
    """Test full-width Unicode characters."""

    def test_fullwidth_ascii(self):
        """Full-width ASCII characters are normalized."""
        # Ｆｏｏ (full-width) → foo (ASCII)
        assert normalize("Ｆｏｏ") == "foo"
        assert normalize("Ｂａｒ") == "bar"


class TestNormalizeArticles:
    """Test leading article stripping."""

    def test_leading_the(self):
        """Leading 'The' is stripped."""
        assert normalize("The Foundation") == "foundation"
        assert normalize("THE HOBBIT") == "hobbit"

    def test_leading_a(self):
        """Leading 'A' is stripped."""
        assert normalize("A Brief History") == "brief history"
        assert normalize("A Tale of Two Cities") == "tale of two cities"

    def test_leading_an(self):
        """Leading 'An' is stripped."""
        assert normalize("An American Dream") == "american dream"
        assert normalize("AN UNEXPECTED JOURNEY") == "unexpected journey"

    def test_non_leading_articles_preserved(self):
        """Non-leading articles are preserved."""
        assert normalize("Theology") == "theology"  # 'the' is not followed by space
        assert normalize("Ant Farm") == "ant farm"  # 'an' is not followed by space
        assert normalize("Apple") == "apple"  # 'a' is not followed by space

    def test_french_articles_not_stripped(self):
        """French articles are not stripped (English-only in v1)."""
        assert normalize("Le Petit Prince") == "le petit prince"
        assert normalize("La Vie en Rose") == "la vie en rose"


class TestNormalizeWhitespace:
    """Test whitespace collapsing."""

    def test_multiple_spaces(self):
        """Multiple spaces collapse to single space."""
        assert normalize("Foo   Bar") == "foo bar"
        assert normalize("  Leading and trailing  ") == "leading and trailing"

    def test_tabs_and_newlines(self):
        """Tabs and newlines collapse to single space."""
        assert normalize("Foo\tBar") == "foo bar"
        assert normalize("Foo\nBar") == "foo bar"
        assert normalize("Foo\r\nBar") == "foo bar"

    def test_mixed_whitespace(self):
        """Mixed whitespace types collapse correctly."""
        assert normalize("Foo  \t\n  Bar") == "foo bar"


class TestNormalizeIdempotence:
    """Test idempotence property."""

    def test_idempotent_empty(self):
        """Normalizing empty string twice is idempotent."""
        assert normalize(normalize("")) == normalize("")

    def test_idempotent_none(self):
        """Normalizing None twice is idempotent."""
        assert normalize(normalize(None)) == normalize(None)

    def test_idempotent_plain(self):
        """Normalizing plain text twice is idempotent."""
        text = "Hello World"
        assert normalize(normalize(text)) == normalize(text)

    def test_idempotent_with_diacritics(self):
        """Normalizing text with diacritics twice is idempotent."""
        text = "Café Français"
        assert normalize(normalize(text)) == normalize(text)

    def test_idempotent_with_articles(self):
        """Normalizing text with articles twice is idempotent."""
        text = "The Great Gatsby"
        assert normalize(normalize(text)) == normalize(text)

    def test_idempotent_with_whitespace(self):
        """Normalizing text with extra whitespace twice is idempotent."""
        text = "  Foo   Bar  "
        assert normalize(normalize(text)) == normalize(text)


class TestNormalizeComplex:
    """Test complex real-world scenarios."""

    def test_book_title_with_article_and_diacritics(self):
        """Complex book title with article and diacritics."""
        assert normalize("The Café Français") == "cafe francais"

    def test_author_name_with_diacritics(self):
        """Author name with diacritics."""
        assert normalize("José María García") == "jose maria garcia"

    def test_title_with_multiple_articles(self):
        """Title with multiple articles (only leading stripped)."""
        assert normalize("The Tale of a King") == "tale of a king"

    def test_title_with_fullwidth_and_diacritics(self):
        """Title with full-width and diacritics."""
        assert normalize("Ｔｈｅ Café") == "cafe"

    def test_title_with_excessive_whitespace(self):
        """Title with excessive whitespace and articles."""
        assert normalize("  The   Great   Gatsby  ") == "great gatsby"

    def test_empty_after_article_strip(self):
        """String that becomes empty after article stripping."""
        # "The" followed by nothing after whitespace collapse
        assert normalize("The") == "the"  # No space after, so not stripped
        assert normalize("The ") == "the"  # Trailing space removed by collapse, no space after "the"

    def test_real_world_book_examples(self):
        """Real-world book title examples."""
        assert normalize("The Lord of the Rings") == "lord of the rings"
        assert normalize("A Game of Thrones") == "game of thrones"
        assert normalize("An Ember in the Ashes") == "ember in the ashes"
        assert normalize("The Name of the Wind") == "name of the wind"
