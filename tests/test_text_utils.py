"""Tests for backend.utils.text HTML stripping utility."""

import pytest

from backend.utils.text import strip_html


class TestStripHtmlBasic:
    """Basic functionality tests."""

    def test_none_input(self) -> None:
        """strip_html(None) returns None."""
        assert strip_html(None) is None

    def test_empty_string(self) -> None:
        """strip_html('') returns ''."""
        assert strip_html("") == ""

    def test_plain_text(self) -> None:
        """Plain text without HTML is returned unchanged."""
        assert strip_html("plain text") == "plain text"


class TestStripHtmlTags:
    """Tests for tag stripping."""

    def test_simple_paragraph(self) -> None:
        """<p>hello</p> returns 'hello'."""
        assert strip_html("<p>hello</p>") == "hello"

    def test_multiple_paragraphs(self) -> None:
        """<p>a</p><p>b</p> returns 'a\\n\\nb' (double newline between)."""
        assert strip_html("<p>a</p><p>b</p>") == "a\n\nb"

    def test_nested_tags(self) -> None:
        """<a href='x'><b>nested</b></a> returns 'nested'."""
        assert strip_html("<a href='x'><b>nested</b></a>") == "nested"

    def test_script_tag_removed(self) -> None:
        """<script>alert(1)</script>safe returns 'safe'."""
        assert strip_html("<script>alert(1)</script>safe") == "safe"


class TestStripHtmlLineBreaks:
    """Tests for line break handling."""

    def test_br_tag(self) -> None:
        """<br/> becomes single newline."""
        assert strip_html("line1<br/>line2") == "line1\nline2"

    def test_br_variants(self) -> None:
        """<br>, <br/>, <br /> all become newline."""
        assert strip_html("a<br>b") == "a\nb"
        assert strip_html("a<br/>b") == "a\nb"
        assert strip_html("a<br />b") == "a\nb"


class TestStripHtmlEntities:
    """Tests for HTML entity decoding."""

    def test_entity_decoding(self) -> None:
        """&nbsp;&amp;&#39; are decoded correctly."""
        result = strip_html("&nbsp;&amp;&#39;")
        assert result == "\u00a0&'"

    def test_unknown_entity(self) -> None:
        """Unknown entities don't crash."""
        result = strip_html("&unknownentity;")
        assert isinstance(result, str)


class TestStripHtmlNewlineCollapse:
    """Tests for newline collapsing."""

    def test_newline_collapse(self) -> None:
        """3+ consecutive newlines collapse to exactly 2."""
        assert strip_html("text\n\n\n\nmore") == "text\n\nmore"

    def test_paragraph_newline_collapse(self) -> None:
        """Multiple paragraphs collapse excess newlines."""
        # <p>a</p> adds \n\n after, <p>b</p> adds \n\n before → \n\n\n\n → collapses to \n\n
        result = strip_html("<p>a</p><p>b</p>")
        assert result == "a\n\nb"


class TestStripHtmlMalformed:
    """Tests for malformed HTML handling."""

    def test_unclosed_paragraph(self) -> None:
        """Unclosed <p> doesn't crash."""
        result = strip_html("<p>unclosed")
        assert isinstance(result, str)
        assert "unclosed" in result

    def test_unclosed_nested(self) -> None:
        """<p><b>unclosed doesn't crash."""
        result = strip_html("<p><b>unclosed")
        assert isinstance(result, str)
        assert "unclosed" in result

    def test_cdata_section(self) -> None:
        """<![CDATA[evil]]> doesn't crash."""
        result = strip_html("<![CDATA[evil]]>")
        assert isinstance(result, str)

    def test_deeply_nested_tags(self) -> None:
        """<p> * 1000 doesn't crash."""
        html_str = "<p>" * 1000
        result = strip_html(html_str)
        assert isinstance(result, str)


class TestStripHtmlWhitespace:
    """Tests for whitespace handling."""

    def test_leading_trailing_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace is stripped."""
        assert strip_html("  hello  ") == "hello"

    def test_internal_whitespace_preserved(self) -> None:
        """Internal whitespace is preserved."""
        assert strip_html("hello   world") == "hello   world"


class TestStripHtmlDivs:
    """Tests for div element handling."""

    def test_div_wrapping(self) -> None:
        """<div>content</div> wraps with single newlines."""
        result = strip_html("<div>content</div>")
        # div adds \n before and \n after, then stripped
        assert "content" in result
