"""Test helper functions and factories for BookOtter tests."""

import os
import zipfile
from datetime import datetime

from backend.models.book import Author, Book, BookStatus


def create_test_epub(path: str, title: str, author: str) -> None:
    """Create a minimal valid EPUB file for testing.

    Args:
        path: File path where EPUB should be created
        title: Book title for metadata
        author: Author name for metadata
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        epub.writestr("META-INF/container.xml", container_xml)

        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uuid_id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="uuid_id">test-{title.replace(" ", "-").lower()}</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chapter1"/>
  </spine>
</package>"""
        epub.writestr("OEBPS/content.opf", content_opf)

        toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="test-{title.replace(" ", "-").lower()}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>{title}</text>
  </docTitle>
  <navMap>
    <navPoint id="navpoint1" playOrder="1">
      <navLabel>
        <text>Chapter 1</text>
      </navLabel>
      <content src="chapter1.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""
        epub.writestr("OEBPS/toc.ncx", toc_ncx)

        chapter_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>{title}</title>
  </head>
  <body>
    <h1>{title}</h1>
    <p>By {author}</p>
    <p>This is a test EPUB file for BookOtter testing.</p>
  </body>
</html>"""
        epub.writestr("OEBPS/chapter1.xhtml", chapter_xhtml)


def create_test_book(db, title: str = "Test Book", author_name: str = None, **kwargs) -> Book:
    """Factory for creating Book records with sensible defaults.

    Args:
        db: SQLAlchemy session
        title: Book title
        author_name: Author name (defaults to title if not provided, for uniqueness)
        **kwargs: Additional Book fields to override defaults

    Returns:
        Created Book instance (not yet committed)
    """
    if author_name is None:
        author_name = f"Author of {title}"

    author = Author(name=author_name, hardcover_id=kwargs.pop("hardcover_id", None))
    db.add(author)
    db.flush()

    defaults = {
        "title": title,
        "author_id": author.id,
        "hardcover_id": kwargs.pop("hardcover_id", f"test-{title.replace(' ', '-').lower()}"),
        "isbn": kwargs.pop("isbn", "978-0-123456-78-9"),
        "status": BookStatus.WANTED.value,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    defaults.update(kwargs)

    book = Book(**defaults)
    db.add(book)
    db.flush()

    return book


def create_test_author(db, name: str = "Test Author", **kwargs) -> Author:
    """Factory for creating Author records with sensible defaults.

    Args:
        db: SQLAlchemy session
        name: Author name
        **kwargs: Additional Author fields to override defaults

    Returns:
        Created Author instance (not yet committed)
    """
    defaults = {
        "name": name,
        "hardcover_id": kwargs.pop("hardcover_id", None),
        "created_at": datetime.utcnow(),
    }
    defaults.update(kwargs)

    author = Author(**defaults)
    db.add(author)
    db.flush()

    return author
