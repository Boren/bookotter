import logging
import re

from backend.clients.prowlarr_client import ProwlarrClient

logger = logging.getLogger(__name__)

PREFERRED_SIZE_MIN = 1 * 1024 * 1024
PREFERRED_SIZE_MAX = 10 * 1024 * 1024

EPUB_RE = re.compile(r"\bEPUB\b", re.IGNORECASE)
NON_EPUB_FORMAT_RE = re.compile(r"\b(AZW3?|MOBI|PDF)\b", re.IGNORECASE)
AUDIOBOOK_RE = re.compile(
    r"\b(M4B|FLAC|audiobook|unabridged|abridged|narrated\s+by|read\s+by|full[- ]cast)\b",
    re.IGNORECASE,
)
AUDIO_CATEGORY_RANGE = range(3000, 4000)
EBOOK_CATEGORY_RANGE = range(7000, 8000)


class SearchService:
    def __init__(self, prowlarr_client: ProwlarrClient):
        self.prowlarr = prowlarr_client

    def search_book(self, title: str, author: str = "") -> list[dict]:
        logger.info(f"Searching for book: '{title}'" + (f" by '{author}'" if author else ""))

        raw_results = self.prowlarr.search_book(title=title, author=author)
        if not raw_results:
            logger.debug(f"No results from Prowlarr for: '{title}'")
            return []

        kept = self.filter_results(raw_results)
        ranked = self.rank_results(kept)
        logger.info(f"Search for '{title}' returned {len(ranked)}/{len(raw_results)} results after classification")
        return ranked

    def filter_results(self, results: list[dict]) -> list[dict]:
        kept: list[dict] = []
        counts = {"ebook": 0, "ebook-other": 0, "unknown": 0, "audiobook": 0, "no-match": 0}
        for r in results:
            verdict, reason = self._classify(r)
            counts[verdict] += 1
            if verdict in ("ebook", "unknown"):
                kept.append({**r, "format_hint": verdict, "format_reason": reason})
        logger.info(
            f"Filter: {len(kept)}/{len(results)} kept "
            f"(ebook={counts['ebook']}, unknown={counts['unknown']}, "
            f"dropped: ebook-other={counts['ebook-other']}, "
            f"audiobook={counts['audiobook']}, no-match={counts['no-match']})"
        )
        return kept

    def rank_results(self, results: list[dict]) -> list[dict]:
        return sorted(results, key=self._rank_score, reverse=True)

    def _classify(self, result: dict) -> tuple[str, str]:
        """
        Returns (verdict, reason). verdict in
            {'audiobook', 'ebook', 'ebook-other', 'unknown', 'no-match'}.
        Layer order matters; the first match wins.
        """
        title = result.get("title") or ""
        category_ids = [
            c.get("id")
            for c in (result.get("categories") or [])
            if isinstance(c, dict) and isinstance(c.get("id"), int)
        ]

        # Layer 1: audiobook keyword in title
        ab = AUDIOBOOK_RE.search(title)
        if ab:
            return "audiobook", f"audiobook keyword: {ab.group()}"

        # Layer 2: audio category
        audio_cats = [c for c in category_ids if c in AUDIO_CATEGORY_RANGE]
        if audio_cats:
            return "audiobook", f"audio category {audio_cats}"

        # Layer 3: explicit EPUB hint (also fires on bundles like "[EPUB MOBI]")
        if EPUB_RE.search(title):
            return "ebook", "EPUB tag in title"

        # Layer 4: explicit non-EPUB format only -- out of v1 scope
        non_epub = NON_EPUB_FORMAT_RE.search(title)
        if non_epub:
            return "ebook-other", f"non-EPUB format tag: {non_epub.group()} (no EPUB found)"

        # Layer 5: book category without format tag -- keep optimistically
        book_cats = [c for c in category_ids if c in EBOOK_CATEGORY_RANGE]
        if book_cats:
            return "unknown", f"book category {book_cats}, no format tag"

        # Layer 6: nothing matched
        return "no-match", "no signals (not audiobook, not in book category, no format tag)"

    def _rank_score(self, result: dict) -> tuple[int, int, int]:
        format_score = 1 if result.get("format_hint") == "ebook" else 0
        seeders = result.get("seeders") or 0
        size = result.get("size") or 0
        size_score = 1 if PREFERRED_SIZE_MIN <= size <= PREFERRED_SIZE_MAX else 0
        return (format_score, seeders, size_score)
