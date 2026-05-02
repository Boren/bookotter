"""
String normalizer for library scanner matching.

Prepares titles and authors for consistent matching by applying a 5-step pipeline:
1. NFKD Unicode decomposition (compatibility decomposition)
2. Strip combining marks (diacritics: é → e, ü → u, ñ → n)
3. Lowercase conversion
4. Collapse whitespace (multiple spaces/tabs/newlines → single space)
5. Strip leading English articles (the, a, an) when followed by whitespace

Note: Article stripping is English-only in v1. Multi-language article support
(le, la, der, die, das, el, los, etc.) is a future enhancement.

Idempotent: normalize(normalize(s)) == normalize(s) for all inputs.
Returns empty string for None and empty inputs; never raises.
"""

import unicodedata


def normalize(s: str | None) -> str:
    """
    Normalize a string for matching.

    Args:
        s: Input string or None

    Returns:
        Normalized string (empty string if input is None or empty)
    """
    if s is None or s == "":
        return ""

    # Step 1: NFKD decomposition (compatibility decomposition)
    decomposed = unicodedata.normalize("NFKD", s)

    # Step 2: Strip combining marks (diacritics)
    # Keep only characters that are not combining marks
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))

    # Step 3: Lowercase
    lowercased = stripped.lower()

    # Step 4: Collapse whitespace (multiple spaces/tabs/newlines → single space)
    # Split on any whitespace and rejoin with single space
    collapsed = " ".join(lowercased.split())

    # Step 5: Strip leading English articles (the, a, an) when followed by whitespace
    # Only strip if article is at the start and followed by a space
    for article in ("the ", "a ", "an "):
        if collapsed.startswith(article):
            collapsed = collapsed[len(article) :]
            break

    return collapsed
