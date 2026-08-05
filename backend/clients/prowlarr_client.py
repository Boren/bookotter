"""
Prowlarr API Client
Handles REST API queries to search for books across configured indexers.
"""

import logging
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

from backend.clients import ConnectionTestResult, classify_request_error
from backend.constants import (
    PROWLARR_RETRY_ATTEMPTS,
    PROWLARR_TIMEOUT,
    RSS_DEFAULT_LIMIT,
    RSS_DEFAULT_MAX_AGE_DAYS,
    RSS_HTTP_TIMEOUT_SECONDS,
)
from backend.errors import FailureReason, PipelineError
from backend.utils.newznab import parse_caps_xml, parse_rss_xml
from backend.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Prowlarr category ID for ebooks/books
BOOK_CATEGORY_ID = 7020


def _parse_retry_after(value: str | None) -> int | None:
    """Parse the Retry-After header value into an integer number of seconds.

    Accepts either an integer (seconds) or an HTTP-date string (RFC 7231 / RFC 2822).
    Returns None when the header is missing or unparseable. Negative deltas are
    clamped to zero. The HTTP-date branch rounds up to the next whole second.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    try:
        return max(0, int(text))
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(text)
    except TypeError, ValueError:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = (dt - datetime.now(UTC)).total_seconds()
    return max(0, math.ceil(delta))


class ProwlarrClient:
    """Client for interacting with the Prowlarr REST API."""

    def __init__(self, api_key: str, base_url: str = "http://localhost:9696"):
        """
        Initialize the Prowlarr client.

        Args:
            api_key: Prowlarr API key from Settings → General → Security
            base_url: Base URL of the Prowlarr instance
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}

    @retry_with_backoff(
        attempts=PROWLARR_RETRY_ATTEMPTS,
        exceptions=(requests.exceptions.RequestException,),
        failure_reason=FailureReason.PROWLARR_UNREACHABLE,
    )
    def _make_request(
        self, endpoint: str, params: dict | None = None, method: str = "GET", json_data: dict | None = None
    ) -> dict | list:
        """
        Make a request to the Prowlarr API with retry logic.

        Args:
            endpoint: API endpoint (e.g., '/api/v1/search')
            params: Optional query parameters
            method: HTTP method (GET, POST, PUT, DELETE)
            json_data: Optional JSON data for POST/PUT requests

        Returns:
            Response data as dictionary or list

        Raises:
            PipelineError: On auth failure (401/403) or after exhausting retries
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.request(
                method=method, url=url, headers=self.headers, params=params, json=json_data, timeout=PROWLARR_TIMEOUT
            )
            # Check for auth errors before raise_for_status to avoid retry
            if response.status_code in (401, 403):
                logger.error(f"Prowlarr authentication failed: {response.status_code}")
                raise PipelineError("Prowlarr authentication failed", FailureReason.PROWLARR_AUTH_FAILED)

            response.raise_for_status()
            return response.json()

        except PipelineError:
            # Re-raise auth errors immediately without retry
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Prowlarr API request failed: {e}")
            raise

    def _normalize_result(self, result: dict) -> dict:
        """
        Normalize a Prowlarr search result to a consistent dict format.

        Args:
            result: Raw result dict from Prowlarr API

        Returns:
            Normalized result dict with consistent keys
        """
        return {
            "guid": result.get("guid"),
            "indexer_id": result.get("indexerId"),
            "indexer": result.get("indexer"),
            "title": result.get("title"),
            "size": result.get("size"),
            "seeders": result.get("seeders"),
            "leechers": result.get("leechers"),
            "download_url": result.get("downloadUrl"),
            "magnet_url": result.get("magnetUrl"),
            "categories": result.get("categories", []),
            "protocol": result.get("protocol"),
            "publish_date": result.get("publishDate"),
        }

    def search(self, query: str, categories: list[int] | None = None, limit: int = 100) -> list[dict]:
        """
        Search for releases across all configured indexers.

        Args:
            query: Search query string
            categories: List of category IDs to filter by (default: book categories)
            limit: Maximum number of results to return

        Returns:
            List of normalized search result dicts
        """
        if categories is None:
            categories = [BOOK_CATEGORY_ID]

        params: dict = {
            "query": query,
            "type": "search",
            "limit": limit,
        }
        # Prowlarr accepts repeated 'categories' params
        params["categories"] = categories

        try:
            results = self._make_request("/api/v1/search", params=params)

            if not results or not isinstance(results, list):
                logger.debug(f"No results found for query: {query}")
                return []

            normalized = [self._normalize_result(r) for r in results]
            logger.debug(f"Prowlarr search for '{query}' returned {len(normalized)} results")
            return normalized

        except Exception as e:
            logger.error(f"Error searching Prowlarr for '{query}': {e}")
            return []

    def search_book(self, title: str, author: str = "", limit: int = 100) -> list[dict]:
        """
        Search for a book by title and optional author.

        Builds a targeted query using title and author, filtered to book categories.

        Args:
            title: Book title
            author: Author name (optional, appended to query when provided)
            limit: Maximum number of results to return

        Returns:
            List of normalized search result dicts
        """
        query = title.strip()
        if author:
            query = f"{query} {author.strip()}"

        params: dict = {
            "query": query,
            "type": "book",
            "categories": [BOOK_CATEGORY_ID],
            "limit": limit,
        }

        try:
            results = self._make_request("/api/v1/search", params=params)

            if not results or not isinstance(results, list):
                logger.debug(f"No book results found for: {query}")
                return []

            normalized = [self._normalize_result(r) for r in results]
            logger.info(f"Prowlarr book search for '{query}' returned {len(normalized)} results")
            return normalized

        except Exception as e:
            logger.error(f"Error searching Prowlarr for book '{query}': {e}")
            return []

    def get_indexers(self) -> list[dict]:
        """
        Get all configured indexers from Prowlarr.

        Returns:
            List of indexer configuration dicts
        """
        try:
            results = self._make_request("/api/v1/indexer")

            if not results or not isinstance(results, list):
                logger.warning("No indexers found in Prowlarr")
                return []

            logger.debug(f"Found {len(results)} indexer(s)")
            return results

        except Exception as e:
            logger.error(f"Error getting Prowlarr indexers: {e}")
            return []

    def test_connection(self) -> ConnectionTestResult:
        """
        Test the connection to Prowlarr API.

        Returns:
            ConnectionTestResult with success status and error details
        """
        try:
            response = self._make_request("/api/v1/system/status")

            if response:
                version = response.get("version", "unknown")
                logger.info(f"Successfully connected to Prowlarr (version: {version})")
                return ConnectionTestResult(
                    success=True,
                    message=f"Connected to Prowlarr (v{version})",
                )
            else:
                logger.error("Could not retrieve system status from Prowlarr")
                return ConnectionTestResult(
                    success=False,
                    error="Could not retrieve system status from Prowlarr",
                    error_type="invalid_response",
                )

        except requests.exceptions.HTTPError as e:
            logger.error(f"Prowlarr connection test failed: {e}")
            result = classify_request_error(e, "Prowlarr")
            # Add Prowlarr-specific guidance for auth errors
            if result.get("error_type") == "auth_failed":
                result["error"] = "Prowlarr API key is invalid. Check Settings > General in Prowlarr."
            return result

        except Exception as e:
            logger.error(f"Prowlarr connection test failed: {e}")
            return classify_request_error(e, "Prowlarr")

    def get_indexer_caps(self, indexer_id: int) -> dict:
        """Fetch the Newznab capabilities document for a single indexer.

        Issues exactly one HTTP request — no retries — and never raises.
        Returns the dict produced by ``parse_caps_xml`` on success, or
        ``{"book_search_supported": False, "categories": [], "error": "<reason>"}``
        on transport / HTTP failure.
        """
        url = f"{self.base_url}/api/v1/indexer/{indexer_id}/newznab"
        params = {"t": "caps"}
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=RSS_HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            return parse_caps_xml(response.text)
        except requests.RequestException as exc:
            logger.warning(f"Failed to fetch caps for indexer {indexer_id}: {exc}")
            return {"book_search_supported": False, "categories": [], "error": str(exc)}

    def fetch_rss(
        self,
        indexer_id: int,
        indexer_name: str,
        max_age_days: int = RSS_DEFAULT_MAX_AGE_DAYS,
        limit: int = RSS_DEFAULT_LIMIT,
    ) -> tuple[list[dict], dict]:
        """Fetch and parse the Newznab book RSS feed for a single indexer.

        Issues exactly one HTTP request — no retries — and never raises.
        Returns ``(items, meta)`` where ``meta`` always carries the keys
        ``status`` (``"ok"`` | ``"rate_limited"`` | ``"error"``),
        ``retry_after_seconds`` (int | None), ``error`` (str | None), and
        ``http_status`` (int | None). On HTTP 429 the ``Retry-After`` header is
        parsed (integer seconds or HTTP-date) into ``retry_after_seconds``.
        """
        url = f"{self.base_url}/api/v1/indexer/{indexer_id}/newznab"
        params: dict[str, str | int] = {"t": "book", "maxage": max_age_days, "limit": limit}

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=RSS_HTTP_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning(f"Request error fetching RSS from {indexer_name}: {exc}")
            return [], {
                "status": "error",
                "retry_after_seconds": None,
                "error": str(exc),
                "http_status": None,
            }

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(f"Indexer {indexer_name} rate-limited (HTTP 429), retry-after={retry_after}s")
            return [], {
                "status": "rate_limited",
                "retry_after_seconds": retry_after,
                "error": None,
                "http_status": 429,
            }

        if response.status_code >= 400:
            logger.warning(f"HTTP {response.status_code} fetching RSS from {indexer_name}")
            return [], {
                "status": "error",
                "retry_after_seconds": None,
                "error": f"HTTP {response.status_code}",
                "http_status": response.status_code,
            }

        items = parse_rss_xml(response.text, indexer_id, indexer_name)
        logger.info(f"Fetched RSS from indexer {indexer_name}: {len(items)} items")
        return items, {
            "status": "ok",
            "retry_after_seconds": None,
            "error": None,
            "http_status": response.status_code,
        }
