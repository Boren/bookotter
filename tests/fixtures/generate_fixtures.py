#!/usr/bin/env python3
"""Generate test EPUB fixtures for testing."""

import os

from ebooklib import epub


def create_test_book_epub(output_path: str) -> None:
    """Create a test EPUB with full metadata."""
    book = epub.EpubBook()

    book.set_identifier("test-book-001")
    book.set_title("Test Book Title")
    book.set_language("en")

    book.add_author("Test Author Name")

    book.set_unique_metadata("DC", "description", "A test book for unit testing")
    book.set_unique_metadata("DC", "publisher", "Test Publisher")

    c1 = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap_01.xhtml",
        lang="en",
    )
    c1.content = "<h1>Chapter 1</h1><p>This is a test chapter.</p>"

    book.add_item(c1)

    book.toc = (c1,)
    book.spine = ["nav", c1]

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_path, book, {})


def create_test_book_no_metadata_epub(output_path: str) -> None:
    """Create a test EPUB with minimal metadata."""
    book = epub.EpubBook()

    book.set_identifier("test-book-no-meta")
    book.set_language("en")

    c1 = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap_01.xhtml",
        lang="en",
    )
    c1.content = "<h1>Chapter 1</h1><p>Minimal content.</p>"

    book.add_item(c1)

    book.toc = (c1,)
    book.spine = ["nav", c1]

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_path, book, {})


if __name__ == "__main__":
    fixtures_dir = os.path.dirname(os.path.abspath(__file__))

    test_book_path = os.path.join(fixtures_dir, "test_book.epub")
    create_test_book_epub(test_book_path)
    print(f"Created {test_book_path}")

    test_book_no_meta_path = os.path.join(fixtures_dir, "test_book_no_metadata.epub")
    create_test_book_no_metadata_epub(test_book_no_meta_path)
    print(f"Created {test_book_no_meta_path}")
