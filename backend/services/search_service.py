import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.clients.prowlarr_client import ProwlarrClient
from backend.constants import EPUB_TITLE_SIMILARITY_THRESHOLD
from backend.services.blocklist_service import BlocklistService
from backend.utils.clock import naive_utcnow
from backend.utils.similarity import author_surname_match, parse_release_title, title_similarity

logger = logging.getLogger(__name__)

PREFERRED_SIZE_MIN = 1 * 1024 * 1024
PREFERRED_SIZE_MAX = 10 * 1024 * 1024

EPUB_RE = re.compile(r"\bEPUB\b", re.IGNORECASE)
EPUB_FILE_RE = re.compile(r"\.epub\b", re.IGNORECASE)
NON_EPUB_FORMAT_RE = re.compile(r"\b(AZW3?|MOBI|PDF)\b", re.IGNORECASE)
# Audiobook detection.
# Strong format/type tags use simple word boundaries (M4B, FLAC, audiobook, etc.).
# "narrated by" / "read by" require non-start-of-string context (preceding non-word char)
# to avoid false positives on book titles like "Read by Moonlight" where the phrase is
# part of the actual title rather than a narrator credit.
AUDIOBOOK_RE = re.compile(
    r"\b(?:M4B|FLAC|audiobook|unabridged|abridged|full[- ]cast)\b"
    r"|(?<=\W)(?:narrated|read)\s+by\b",
    re.IGNORECASE,
)
# Omnibus/collection detection.
# Named patterns so query and release signals compare as classes: a query
# containing "Books 1-3" suppresses any book-range signal in a release,
# not just the identical text. Ranges require an explicit N-M span so
# single-volume markers ("Book 7") never match.
OMNIBUS_SIGNAL_RES: dict[str, re.Pattern] = {
    "omnibus": re.compile(r"\bomnibus\b", re.IGNORECASE),
    "trilogy": re.compile(r"\btrilogy\b", re.IGNORECASE),
    "duology": re.compile(r"\bduology\b", re.IGNORECASE),
    "quadrilogy": re.compile(r"\bquadrilogy\b", re.IGNORECASE),
    "box-set": re.compile(r"\bbox(?:ed)?[ -]?set\b", re.IGNORECASE),
    "collection": re.compile(r"\bcollection\b", re.IGNORECASE),
    "anthology": re.compile(r"\banthology\b", re.IGNORECASE),
    "complete-series": re.compile(r"\bcomplete series\b", re.IGNORECASE),
    "book-range": re.compile(r"\bbooks?\s*\d+\s*[-–—]\s*\d+\b", re.IGNORECASE),
    "hash-range": re.compile(r"#\d+\s*[-–—]\s*\d+"),
    "vol-range": re.compile(r"\bvol(?:ume)?s?\.?\s*\d+\s*[-–—]\s*\d+\b", re.IGNORECASE),
}


def omnibus_signals(text: str) -> set[str]:
    """Names of omnibus/collection markers present in a release or query title."""
    return {name for name, pattern in OMNIBUS_SIGNAL_RES.items() if pattern.search(text)}


AUDIO_CATEGORY_RANGE = range(3000, 4000)
EBOOK_CATEGORY_RANGE = range(7000, 8000)


@dataclass
class ScoredResult:
    guid: str | None
    indexer_id: int | None
    indexer: str | None
    title: str | None
    size: int | None
    seeders: int | None
    leechers: int | None
    download_url: str | None
    magnet_url: str | None
    publish_date: str | None
    protocol: str | None
    categories: list[dict] = field(default_factory=list)
    age_days: float = 0.0
    title_similarity: float = 1.0
    author_match: bool = False
    rejections: list[str] = field(default_factory=list)
    approved: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class SearchService:
    def __init__(self, prowlarr_client: ProwlarrClient, db: Session | None = None):
        self.prowlarr = prowlarr_client
        self.db = db

    def search_book(self, title: str, author: str = "") -> list[ScoredResult]:
        logger.info(f"Searching for book: '{title}'" + (f" by '{author}'" if author else ""))

        raw_results = self.prowlarr.search_book(title=title, author=author)
        if not raw_results:
            logger.debug(f"No results from Prowlarr for: '{title}'")
            return []

        blocklisted_set = self._blocklist_set()
        scored = [
            self._evaluate(result, blocklisted_set, query_title=title, query_author=author) for result in raw_results
        ]
        ranked = self._rank(scored)
        approved_count = sum(1 for result in ranked if result.approved)
        logger.info(f"Search for '{title}' returned {approved_count}/{len(raw_results)} approved results")
        return ranked

    def filter_results(self, results: list[dict]) -> list[dict]:
        blocklisted_set = self._blocklist_set()
        return [result.to_dict() for result in self._rank([self._evaluate(raw, blocklisted_set) for raw in results])]

    def rank_results(self, results: list[dict]) -> list[dict]:
        blocklisted_set = self._blocklist_set()
        normalized: list[ScoredResult] = [
            self._coerce_result(result)
            if "approved" in result or "rejections" in result or "age_days" in result
            else self._evaluate(result, blocklisted_set)
            for result in results
        ]
        ranked = self._rank(normalized)
        return [result.to_dict() for result in ranked]

    def evaluate_and_rank(
        self,
        raw_results: list[dict],
        query_title: str = "",
        query_author: str = "",
    ) -> list[ScoredResult]:
        """Evaluate and rank a pre-fetched list of result dicts (e.g., from RSS).
        Used by RssSyncService to reuse existing filtering and matching logic
        without performing a Prowlarr search."""
        blocklisted_set = self._blocklist_set()
        scored = [
            self._evaluate(raw, blocklisted_set, query_title=query_title, query_author=query_author)
            for raw in raw_results
        ]
        return self._rank(scored)

    def _evaluate(
        self,
        raw: dict,
        blocklisted_set: set[tuple[str, str]],
        query_title: str = "",
        query_author: str = "",
    ) -> ScoredResult:
        verdict, reason = self._classify(raw)
        title = raw.get("title") or ""
        size = raw.get("size") or 0
        seeders = raw.get("seeders") or 0
        protocol = raw.get("protocol") or ""
        indexer = raw.get("indexer")
        guid = raw.get("guid")
        rejections: list[str] = []

        if AUDIOBOOK_RE.search(title):
            rejections.append("Audiobook")

        if query_title:
            release_only_signals = omnibus_signals(title) - omnibus_signals(query_title)
            if release_only_signals:
                rejections.append("Omnibus/collection")

        if indexer and guid and (indexer, guid) in blocklisted_set:
            rejections.append("Blocklisted")

        if protocol == "torrent" and seeders < 1:
            rejections.append("No seeders")

        if size < 10_000:
            rejections.append("Size too small")

        if size > 500 * 1024 * 1024:
            rejections.append("Size too large")

        if verdict == "ebook-other":
            rejections.append(f"Non-EPUB format detected ({reason})")

        if verdict == "no-match":
            rejections.append("No book signals detected")

        # Reject "unknown" verdict (book category but no format tag) unless title contains
        # an explicit .epub filename — defends against Prowlarr returning ambiguous results.
        if verdict == "unknown" and not EPUB_FILE_RE.search(title):
            rejections.append("No candidate matches title")

        # Compute similarity scores against the search query (only meaningful when querying).
        result_title = raw.get("title") or ""
        result_author = raw.get("author") or ""
        title_sim = 1.0
        author_match = False
        if query_title:
            # Release names are typically 'Title by Author [tags]' — compare against
            # both the raw name and the parsed title part so tags/author noise
            # doesn't sink an exact title match.
            parsed_title, parsed_author = parse_release_title(result_title)
            title_sim = max(
                title_similarity(query_title, result_title),
                title_similarity(query_title, parsed_title),
            )
            authors_a = [query_author] if query_author else []
            authors_b = [author for author in (result_author, parsed_author) if author]
            author_match = author_surname_match(authors_a, authors_b)
            # Reject if title similarity below threshold AND no author match — protects
            # against Prowlarr returning unrelated books that happen to share keywords.
            if (
                title_sim < EPUB_TITLE_SIMILARITY_THRESHOLD
                and not author_match
                and "No candidate matches title" not in rejections
            ):
                rejections.append("No candidate matches title")

        publish_date = raw.get("publish_date")
        age_days = self._calculate_age_days(publish_date)

        return ScoredResult(
            guid=guid,
            indexer_id=raw.get("indexer_id"),
            indexer=indexer,
            title=raw.get("title"),
            size=raw.get("size"),
            seeders=raw.get("seeders"),
            leechers=raw.get("leechers"),
            download_url=raw.get("download_url"),
            magnet_url=raw.get("magnet_url"),
            publish_date=publish_date,
            protocol=raw.get("protocol"),
            categories=raw.get("categories") or [],
            age_days=age_days,
            title_similarity=title_sim,
            author_match=author_match,
            rejections=rejections,
            approved=len(rejections) == 0,
        )

    def _blocklist_set(self) -> set[tuple[str, str]]:
        if self.db is None:
            return set()
        return BlocklistService(self.db).get_set()

    def _rank(self, results: list[ScoredResult]) -> list[ScoredResult]:
        return sorted(
            results,
            key=lambda result: (
                1 if result.approved else 0,
                1 if result.author_match else 0,
                result.title_similarity or 0.0,
                result.seeders or 0,
                -(result.age_days or 0.0),
            ),
            reverse=True,
        )

    def _coerce_result(self, result: dict) -> ScoredResult:
        publish_date = result.get("publish_date")
        rejections = list(result.get("rejections") or [])
        approved = result.get("approved")
        if approved is None:
            approved = len(rejections) == 0

        return ScoredResult(
            guid=result.get("guid"),
            indexer_id=result.get("indexer_id"),
            indexer=result.get("indexer"),
            title=result.get("title"),
            size=result.get("size"),
            seeders=result.get("seeders"),
            leechers=result.get("leechers"),
            download_url=result.get("download_url"),
            magnet_url=result.get("magnet_url"),
            publish_date=publish_date,
            protocol=result.get("protocol"),
            categories=result.get("categories") or [],
            age_days=result.get("age_days", self._calculate_age_days(publish_date)),
            title_similarity=result.get("title_similarity", 1.0),
            author_match=result.get("author_match", False),
            rejections=rejections,
            approved=approved,
        )

    def _calculate_age_days(self, publish_date: str | None) -> float:
        if not publish_date:
            return 0.0

        try:
            parsed = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return float((naive_utcnow() - parsed).days)
        except ValueError:
            logger.debug(f"Could not parse publish date: {publish_date}")
            return 0.0

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

        ab = AUDIOBOOK_RE.search(title)
        if ab:
            return "audiobook", f"audiobook keyword: {ab.group()}"

        audio_cats = [c for c in category_ids if c in AUDIO_CATEGORY_RANGE]
        if audio_cats:
            return "audiobook", f"audio category {audio_cats}"

        if EPUB_RE.search(title):
            return "ebook", "EPUB tag in title"

        non_epub = NON_EPUB_FORMAT_RE.search(title)
        if non_epub:
            return "ebook-other", f"non-EPUB format tag: {non_epub.group()} (no EPUB found)"

        book_cats = [c for c in category_ids if c in EBOOK_CATEGORY_RANGE]
        if book_cats:
            return "unknown", f"book category {book_cats}, no format tag"

        return "no-match", "no signals (not audiobook, not in book category, no format tag)"
