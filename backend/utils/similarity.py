"""
Text similarity utilities for book title and author matching.
Uses stdlib only (difflib, unicodedata, re) — no third-party deps.
"""

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_for_match(s: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, strip punctuation."""
    # NFKD decomposition strips diacritics
    s = unicodedata.normalize("NFKD", s)
    # Remove non-ASCII characters (diacritics become separate chars and get removed)
    s = s.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    s = s.lower()
    # Remove punctuation except spaces and alphanumeric
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_similarity(a: str, b: str) -> float:
    """Return 0.0-1.0 similarity score using normalized SequenceMatcher."""
    na = normalize_for_match(a)
    nb = normalize_for_match(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _extract_surname(full_name: str) -> str:
    """Extract surname from 'First Last' or 'Last, First' format."""
    name = full_name.strip()
    if "," in name:
        # "Last, First" format
        return normalize_for_match(name.split(",")[0])
    else:
        # "First Last" format — last word is surname
        parts = name.split()
        return normalize_for_match(parts[-1]) if parts else ""


def author_surname_match(authors_a: list[str], authors_b: list[str]) -> bool:
    """Return True if any surname from authors_a matches any surname from authors_b (case-insensitive)."""
    surnames_a = {_extract_surname(a) for a in authors_a if a.strip()}
    surnames_b = {_extract_surname(b) for b in authors_b if b.strip()}
    return bool(surnames_a & surnames_b)
