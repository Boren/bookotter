"""
HTML stripping utility for cleaning descriptions and text content.
Removes HTML tags while preserving text, handling block elements and entities.
"""

import html
import re
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Private HTML parser that extracts text content and handles block elements."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle opening tags. Inject newlines for block elements and <br>."""
        tag_lower = tag.lower()

        if tag_lower == "br":
            self.text_parts.append("\n")
        elif tag_lower == "p":
            self.text_parts.append("\n\n")
            self.tag_stack.append(tag_lower)
        elif tag_lower == "div":
            self.text_parts.append("\n")
            self.tag_stack.append(tag_lower)
        else:
            self.tag_stack.append(tag_lower)

    def handle_endtag(self, tag: str) -> None:
        """Handle closing tags. Inject newlines for block elements."""
        tag_lower = tag.lower()

        if tag_lower == "p":
            self.text_parts.append("\n\n")
            if self.tag_stack and self.tag_stack[-1] == tag_lower:
                self.tag_stack.pop()
        elif tag_lower == "div":
            self.text_parts.append("\n")
            if self.tag_stack and self.tag_stack[-1] == tag_lower:
                self.tag_stack.pop()
        else:
            if self.tag_stack and self.tag_stack[-1] == tag_lower:
                self.tag_stack.pop()

    def handle_data(self, data: str) -> None:
        """Handle text data. Decode HTML entities."""
        if data:
            decoded = html.unescape(data)
            self.text_parts.append(decoded)

    def handle_entityref(self, name: str) -> None:
        """Handle named entities like &nbsp; &amp; etc."""
        # html.unescape handles these, but we capture them here for completeness
        try:
            decoded = html.unescape(f"&{name};")
            self.text_parts.append(decoded)
        except Exception:
            # If unescape fails, keep the entity as-is
            self.text_parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        """Handle numeric character references like &#39; &#x27;."""
        try:
            decoded = html.unescape(f"&#{name};")
            self.text_parts.append(decoded)
        except Exception:
            # If unescape fails, keep the reference as-is
            self.text_parts.append(f"&#{name};")

    def get_text(self) -> str:
        """Return accumulated text."""
        return "".join(self.text_parts)


def strip_html(text: str | None) -> str | None:
    """
    Strip HTML tags from text, preserving text content and handling block elements.

    Args:
        text: HTML string or None

    Returns:
        Stripped text with entities decoded, or None if input is None.
        - <br>, <br/>, <br /> → single newline
        - <p>...</p> → wrapped with double newlines
        - <div>...</div> → wrapped with single newlines
        - All other tags → stripped, inner text kept
        - 3+ consecutive newlines → collapsed to exactly 2
        - Leading/trailing whitespace → stripped

    Handles malformed HTML gracefully without raising exceptions.
    """
    if text is None:
        return None

    if not text:
        return ""

    try:
        parser = _HTMLStripper()
        parser.feed(text)
        result = parser.get_text()
    except Exception:
        # If parsing fails, return empty string (malformed input)
        return ""

    # Collapse 3+ consecutive newlines to exactly 2
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Strip leading/trailing whitespace
    result = result.strip()

    return result
