"""
Prowlarr API Client
Handles REST API queries to search for books across configured indexers.
"""

import logging

import requests

from backend.clients import ConnectionTestResult, classify_request_error

logger = logging.getLogger(__name__)

# Prowlarr category ID for ebooks/books
BOOK_CATEGORY_ID = 7020


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

    def _make_request(
        self, endpoint: str, params: dict | None = None, method: str = "GET", json_data: dict | None = None
    ) -> dict | list:
        """
        Make a request to the Prowlarr API.

        Args:
            endpoint: API endpoint (e.g., '/api/v1/search')
            params: Optional query parameters
            method: HTTP method (GET, POST, PUT, DELETE)
            json_data: Optional JSON data for POST/PUT requests

        Returns:
            Response data as dictionary or list

        Raises:
            requests.exceptions.RequestException: If the request fails
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.request(
                method=method, url=url, headers=self.headers, params=params, json=json_data, timeout=30
            )
            response.raise_for_status()
            return response.json()

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
