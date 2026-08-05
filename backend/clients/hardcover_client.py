"""
Hardcover API Client
Handles GraphQL queries to fetch the user's book lists with offset-based
pagination and resilient retry semantics.
"""

import json
import logging
import time

import requests

from backend import __app_name__, __github_url__, __version__
from backend.clients import ConnectionTestResult, classify_request_error
from backend.constants import (
    HARDCOVER_RATE_LIMIT_DELAY,
    HARDCOVER_RETRY_ATTEMPTS,
    HARDCOVER_TIMEOUT,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
)
from backend.errors import FailureReason, PipelineError

logger = logging.getLogger(__name__)

HARDCOVER_PAGE_SIZE = 50


class HardcoverClient:
    """Client for interacting with the Hardcover GraphQL API."""

    def __init__(self, api_token: str, api_url: str = "https://api.hardcover.app/v1/graphql"):
        """
        Initialize the Hardcover client.

        Args:
            api_token: Hardcover API token from https://hardcover.app/account/api
            api_url: GraphQL endpoint URL
        """
        self.api_token = api_token
        self.api_url = api_url
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": api_token,
            "User-Agent": f"{__app_name__}/{__version__} ({__github_url__})",
        }

    def _make_request(self, query: str, variables: dict | None = None) -> dict:
        """
        Make a GraphQL request to the Hardcover API with retry + backoff.

        Behavior:
            - 401/403 → raise PipelineError(HARDCOVER_AUTH_FAILED) immediately, no retry
            - 429 → parse Retry-After header (seconds), sleep, then retry.
              On final failure raise PipelineError(HARDCOVER_RATE_LIMITED).
            - requests.RequestException (timeout, connection errors) →
              retry with exponential backoff. On final failure raise
              PipelineError(HARDCOVER_UNREACHABLE).
            - Other HTTP errors (4xx/5xx not above) → treated as network errors
              and retried with HARDCOVER_UNREACHABLE failure tag on exhaustion.

        Args:
            query: GraphQL query string
            variables: Optional variables for the query

        Returns:
            Response data as dictionary

        Raises:
            PipelineError: On auth failure, rate limit exhaustion, or after
              exhausting retries on network/HTTP errors.
        """
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        last_network_exc: Exception | None = None

        for attempt in range(1, HARDCOVER_RETRY_ATTEMPTS + 1):
            is_last_attempt = attempt == HARDCOVER_RETRY_ATTEMPTS

            try:
                response = requests.post(
                    self.api_url,
                    json=payload,
                    headers=self.headers,
                    timeout=HARDCOVER_TIMEOUT,
                )
            except requests.exceptions.RequestException as exc:
                last_network_exc = exc
                if is_last_attempt:
                    logger.error("Hardcover request failed after %d attempts: %s", attempt, exc)
                    raise PipelineError(str(exc), FailureReason.HARDCOVER_UNREACHABLE) from exc
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                logger.warning(
                    "Hardcover network error on attempt %d/%d (sleeping %.1fs): %s",
                    attempt,
                    HARDCOVER_RETRY_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue

            if response.status_code in (401, 403):
                logger.error("Hardcover authentication failed (HTTP %d)", response.status_code)
                raise PipelineError(
                    f"Hardcover authentication failed (HTTP {response.status_code})",
                    FailureReason.HARDCOVER_AUTH_FAILED,
                )

            if response.status_code == 429:
                if is_last_attempt:
                    logger.error("Hardcover rate limit exceeded after %d attempts", attempt)
                    raise PipelineError(
                        "Hardcover rate limit exceeded",
                        FailureReason.HARDCOVER_RATE_LIMITED,
                    )
                retry_after = self._parse_retry_after(response.headers.get("Retry-After"), attempt)
                logger.warning(
                    "Hardcover rate-limited on attempt %d/%d (sleeping %.1fs)",
                    attempt,
                    HARDCOVER_RETRY_ATTEMPTS,
                    retry_after,
                )
                time.sleep(retry_after)
                continue

            if not response.ok:
                http_exc = requests.exceptions.HTTPError(
                    f"HTTP {response.status_code}: {response.reason}",
                    response=response,
                )
                last_network_exc = http_exc
                if is_last_attempt:
                    logger.error("Hardcover HTTP error after %d attempts: %s", attempt, http_exc)
                    raise PipelineError(str(http_exc), FailureReason.HARDCOVER_UNREACHABLE) from http_exc
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                logger.warning(
                    "Hardcover HTTP %d on attempt %d/%d (sleeping %.1fs)",
                    response.status_code,
                    attempt,
                    HARDCOVER_RETRY_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
                continue

            data = response.json()
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                raise PipelineError(
                    f"GraphQL query failed: {data['errors']}",
                    FailureReason.HARDCOVER_UNREACHABLE,
                )

            time.sleep(HARDCOVER_RATE_LIMIT_DELAY)
            return data

        raise PipelineError(
            str(last_network_exc) if last_network_exc else "Hardcover request failed",
            FailureReason.HARDCOVER_UNREACHABLE,
        )

    @staticmethod
    def _parse_retry_after(header_value: str | None, attempt: int) -> float:
        """
        Parse the Retry-After header into a sleep duration in seconds.

        Falls back to exponential backoff based on HARDCOVER_RATE_LIMIT_DELAY
        when the header is missing or unparseable.
        """
        if header_value:
            try:
                return float(header_value)
            except TypeError, ValueError:
                pass
        return HARDCOVER_RATE_LIMIT_DELAY * (2 ** (attempt - 1))

    def get_books_by_status(self, status_ids: list[int]) -> list[dict]:
        """
        Fetch books with specified status IDs from the user's library.

        Uses offset-based pagination (HARDCOVER_PAGE_SIZE per page) and
        deduplicates by hardcover book id across pages.

        Status IDs:
        - 1: Want to Read
        - 2: Currently Reading
        - 3: Read

        Args:
            status_ids: List of status IDs to fetch

        Returns:
            List of book dictionaries with title, author, and ISBN information
        """
        query = """
        query GetBooksByStatus($statusIds: [Int!]!, $limit: Int!, $offset: Int!) {
          me {
            user_books(where: {status_id: {_in: $statusIds}}, limit: $limit, offset: $offset) {
              status_id
              rating
              date_added
               book {
                 id
                 title
                 slug
                 subtitle
                 description
                 cached_contributors
                 image {
                   url
                 }
                 book_series {
                   position
                   series {
                     name
                     slug
                   }
                 }
                 editions {
                   id
                   title
                   isbn_10
                   isbn_13
                   edition_format
                   pages
                   release_date
                   publisher {
                     name
                   }
                 }
                 contributions {
                   author {
                     id
                     name
                   }
                 }
               }
            }
          }
        }
        """

        status_names = {1: "Want to Read", 2: "Currently Reading", 3: "Read"}
        status_labels = [status_names.get(sid, f"Status {sid}") for sid in status_ids]
        logger.info(f"Fetching books from Hardcover with statuses: {', '.join(status_labels)}")

        books_by_id: dict[int | str, dict] = {}
        books_without_id: list[dict] = []
        offset = 0
        page_index = 0

        try:
            while True:
                page_index += 1
                variables = {
                    "statusIds": status_ids,
                    "limit": HARDCOVER_PAGE_SIZE,
                    "offset": offset,
                }
                response = self._make_request(query, variables)

                user_books = self._extract_user_books(response)
                page_count = len(user_books)
                logger.debug(
                    "Hardcover page %d: offset=%d returned %d books",
                    page_index,
                    offset,
                    page_count,
                )

                for user_book in user_books:
                    book = self._parse_user_book(user_book)
                    hc_id = book.get("hardcover_id")
                    if hc_id is not None:
                        books_by_id[hc_id] = book
                    else:
                        books_without_id.append(book)

                if page_count < HARDCOVER_PAGE_SIZE:
                    break
                offset += HARDCOVER_PAGE_SIZE

            books = list(books_by_id.values()) + books_without_id
            logger.info(
                "Found %d books with specified statuses (across %d page(s))",
                len(books),
                page_index,
            )
            return books

        except PipelineError:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch books from Hardcover: {e}")
            raise

    @staticmethod
    def _extract_user_books(response: dict) -> list[dict]:
        """Extract the user_books list from a Hardcover GraphQL response."""
        me_data = response.get("data", {}).get("me", [])
        if isinstance(me_data, list) and len(me_data) > 0:
            return me_data[0].get("user_books", []) or []
        if isinstance(me_data, dict):
            return me_data.get("user_books", []) or []
        return []

    @staticmethod
    def _parse_user_book(user_book: dict) -> dict:
        """Convert a raw user_book GraphQL node into the BookOtter book dict."""
        book_data = user_book.get("book", {}) or {}

        # Extract authors
        authors: list[str] = []
        if book_data.get("contributions"):
            authors = [contrib["author"]["name"] for contrib in book_data["contributions"]]
        elif book_data.get("cached_contributors"):
            authors = [book_data["cached_contributors"]]

        # Extract ISBNs from all editions
        isbn_list: list[str] = []
        editions = book_data.get("editions", []) or []
        for edition in editions:
            if edition.get("isbn_13"):
                isbn_list.append(edition["isbn_13"])
            if edition.get("isbn_10"):
                isbn_list.append(edition["isbn_10"])

        # Extract cover image URL
        image_data = book_data.get("image", {}) or {}
        cover_url = image_data.get("url") if image_data else None

        # Extract series information (take first series if multiple)
        book_series_list = book_data.get("book_series", []) or []
        series_name = None
        series_position = None
        if book_series_list:
            first_series = book_series_list[0] or {}
            series_data = first_series.get("series", {}) or {}
            series_name = series_data.get("name") if series_data else None
            series_position = first_series.get("position")

        return {
            "title": book_data.get("title", ""),
            "subtitle": book_data.get("subtitle", ""),
            "authors": authors,
            "author_string": ", ".join(authors) if authors else "",
            "isbns": list(set(isbn_list)),  # Remove duplicates
            "hardcover_id": book_data.get("id"),
            "slug": book_data.get("slug", ""),
            "cover_url": cover_url,
            "series_name": series_name,
            "series_position": series_position,
            "date_added": user_book.get("date_added", ""),
            "status_id": user_book.get("status_id"),  # 1=want_to_read, 2=reading, 3=read
            "editions": editions,
        }

    def get_want_to_read_books(self) -> list[dict]:
        """
        Fetch all books in the user's "want to read" list.

        This is a convenience wrapper around get_books_by_status([1]).

        Returns:
            List of book dictionaries with title, author, and ISBN information
        """
        return self.get_books_by_status([1])

    def search_books(self, query: str, limit: int = 5) -> list[dict]:
        """Search Hardcover for books matching free-text query.

        Used by the library scanner to bootstrap unmatched EPUBs into the
        local Book table. Returns up to `limit` matches with id, title,
        authors, and (when present) ISBN.

        Args:
            query: Free-text search string (title, author, ISBN, etc.)
            limit: Max number of results to return (default 5)

        Returns:
            List of dicts shaped like:
            [
                {
                    "id": <int>,                     # Hardcover book ID
                    "title": <str>,
                    "author_names": [<str>, ...],    # may be empty
                    "isbns": [<str>, ...],           # may be empty
                },
                ...
            ]
            Empty list if no results.

        Raises:
            Same exceptions as other HardcoverClient methods on auth/network failure.
        """
        gql_query = """
        query SearchBooks($query: String!, $perPage: Int!) {
          search(query: $query, query_type: "book", per_page: $perPage, page: 1) {
            ids
            results
            error
            page
            per_page
          }
        }
        """
        variables = {"query": query, "perPage": limit}
        response = self._make_request(gql_query, variables)

        search_payload = (response.get("data") or {}).get("search") or {}
        if search_payload.get("error"):
            logger.warning("Hardcover search returned error: %s", search_payload["error"])

        raw_results = search_payload.get("results")
        if raw_results is None:
            return []

        # Hardcover returns `results` as jsonb. It may arrive as a parsed list
        # or as a JSON-encoded string depending on how the server serializes it.
        if isinstance(raw_results, str):
            try:
                raw_results = json.loads(raw_results)
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to parse Hardcover search results JSON: %s", exc)
                return []

        # Typesense-style payload may wrap entries under "hits" or be a flat list.
        if isinstance(raw_results, dict):
            entries = raw_results.get("hits") or raw_results.get("results") or []
        elif isinstance(raw_results, list):
            entries = raw_results
        else:
            logger.warning("Unexpected Hardcover search results shape: %s", type(raw_results).__name__)
            return []

        books: list[dict] = []
        for entry in entries[:limit]:
            book = self._parse_search_entry(entry)
            if book is not None:
                books.append(book)

        return books

    def get_book_by_id(self, book_id: int) -> dict | None:
        """Fetch a single Hardcover book by its ID.

        Returns the same shape as `search_books` entries
        ({"id", "title", "author_names", "isbns"}), or None when the book
        does not exist.

        Raises:
            Same exceptions as other HardcoverClient methods on auth/network failure.
        """
        gql_query = """
        query GetBookById($id: Int!) {
          books_by_pk(id: $id) {
            id
            title
            contributions {
              author {
                name
              }
            }
            editions {
              isbn_10
              isbn_13
            }
          }
        }
        """
        response = self._make_request(gql_query, {"id": book_id})

        book = (response.get("data") or {}).get("books_by_pk")
        if not isinstance(book, dict) or book.get("id") is None or not book.get("title"):
            return None

        author_names = [
            str(contribution["author"]["name"])
            for contribution in book.get("contributions") or []
            if isinstance(contribution, dict) and (contribution.get("author") or {}).get("name")
        ]
        isbns = [
            str(isbn)
            for edition in book.get("editions") or []
            if isinstance(edition, dict)
            for isbn in (edition.get("isbn_13"), edition.get("isbn_10"))
            if isbn
        ]

        return {
            "id": int(book["id"]),
            "title": str(book["title"]),
            "author_names": author_names,
            "isbns": isbns,
        }

    @staticmethod
    def _parse_search_entry(entry: object) -> dict | None:
        """Extract a normalized book dict from a single Hardcover search entry.

        Returns None when the entry is malformed (missing id or title) so the
        caller can skip it gracefully.
        """
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict Hardcover search entry: %s", type(entry).__name__)
            return None

        # Typesense responses may nest the actual book under a "document" key.
        nested = entry.get("document")
        document: dict = nested if isinstance(nested, dict) else entry

        book_id = document.get("id")
        title = document.get("title")
        if book_id is None or not title:
            logger.warning("Skipping malformed Hardcover search entry (missing id/title)")
            return None

        try:
            book_id_int = int(book_id)
        except TypeError, ValueError:
            logger.warning("Skipping Hardcover search entry with non-integer id: %r", book_id)
            return None

        author_names = document.get("author_names") or []
        if not isinstance(author_names, list):
            author_names = []

        isbns = document.get("isbns") or []
        if not isinstance(isbns, list):
            isbns = []

        return {
            "id": book_id_int,
            "title": str(title),
            "author_names": [str(a) for a in author_names if a],
            "isbns": [str(i) for i in isbns if i],
        }

    def test_connection(self) -> ConnectionTestResult:
        """
        Test the connection to Hardcover API.

        Returns:
            ConnectionTestResult with success status and error details
        """
        query = """
        {
          me {
            id
            name
          }
        }
        """

        try:
            response = self._make_request(query)

            # Extract user data (me is returned as a list with one element)
            me_data = response.get("data", {}).get("me", [])

            if isinstance(me_data, list) and len(me_data) > 0:
                user_data = me_data[0]
            elif isinstance(me_data, dict):
                user_data = me_data
            else:
                logger.error("Could not retrieve user data from Hardcover")
                return ConnectionTestResult(
                    success=False,
                    error="Could not retrieve user data from Hardcover",
                    error_type="invalid_response",
                )

            if user_data:
                username = user_data.get("name", "Unknown")
                logger.info(f"Successfully connected to Hardcover as: {username}")
                return ConnectionTestResult(
                    success=True,
                    message=f"Connected to Hardcover as {username}",
                )
            else:
                logger.error("Could not retrieve user data from Hardcover")
                return ConnectionTestResult(
                    success=False,
                    error="Could not retrieve user data from Hardcover",
                    error_type="invalid_response",
                )

        except PipelineError as e:
            logger.error(f"Hardcover connection test failed: {e}")
            if e.reason == FailureReason.HARDCOVER_AUTH_FAILED:
                return ConnectionTestResult(
                    success=False,
                    error=("Hardcover API token is invalid or expired. Get a new token from hardcover.app/account/api"),
                    error_type="auth_failed",
                )
            if e.reason == FailureReason.HARDCOVER_RATE_LIMITED:
                return ConnectionTestResult(
                    success=False,
                    error="Rate limit exceeded (HTTP 429). Wait a moment and try again.",
                    error_type="rate_limited",
                )
            return ConnectionTestResult(
                success=False,
                error=str(e),
                error_type="network_error",
            )

        except requests.exceptions.HTTPError as e:
            logger.error(f"Hardcover connection test failed: {e}")
            result = classify_request_error(e, "Hardcover")
            # Add Hardcover-specific guidance for auth errors
            if result.get("error_type") == "auth_failed":
                result["error"] = (
                    "Hardcover API token is invalid or expired. Get a new token from hardcover.app/account/api"
                )
            return result

        except Exception as e:
            logger.error(f"Hardcover connection test failed: {e}")
            return classify_request_error(e, "Hardcover")
