import logging

from backend.clients.prowlarr_client import ProwlarrClient

logger = logging.getLogger(__name__)

PREFERRED_SIZE_MIN = 1 * 1024 * 1024
PREFERRED_SIZE_MAX = 10 * 1024 * 1024


class SearchService:
    def __init__(self, prowlarr_client: ProwlarrClient):
        self.prowlarr = prowlarr_client

    def search_book(self, title: str, author: str = "") -> list[dict]:
        logger.info(f"Searching for book: '{title}'" + (f" by '{author}'" if author else ""))

        raw_results = self.prowlarr.search_book(title=title, author=author)

        if not raw_results:
            logger.debug(f"No results from Prowlarr for: '{title}'")
            return []

        filtered = self.filter_results(raw_results)
        logger.debug(f"After EPUB filter: {len(filtered)}/{len(raw_results)} results remain")

        ranked = self.rank_results(filtered)
        logger.info(f"Search for '{title}' returned {len(ranked)} ranked EPUB results")

        return ranked

    def filter_results(self, results: list[dict]) -> list[dict]:
        epub_results = [r for r in results if self._is_epub(r)]
        logger.debug(f"Filtered {len(results) - len(epub_results)} non-EPUB results")
        return epub_results

    def rank_results(self, results: list[dict]) -> list[dict]:
        return sorted(results, key=self._rank_score, reverse=True)

    def _is_epub(self, result: dict) -> bool:
        title = (result.get("title") or "").lower()
        return ".epub" in title

    def _rank_score(self, result: dict) -> tuple[int, int]:
        seeders = result.get("seeders") or 0
        size = result.get("size") or 0
        size_score = 1 if PREFERRED_SIZE_MIN <= size <= PREFERRED_SIZE_MAX else 0
        return (seeders, size_score)
