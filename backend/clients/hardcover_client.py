"""
Hardcover API Client
Handles GraphQL queries to fetch the user's "want to read" list.
"""

import logging
import time

import requests

from backend import __app_name__, __github_url__, __version__
from backend.clients import ConnectionTestResult, classify_request_error

logger = logging.getLogger(__name__)


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
        self.request_delay = 1.0  # 1 second delay to respect rate limiting (60 req/min)

    def _make_request(self, query: str, variables: dict | None = None) -> dict:
        """
        Make a GraphQL request to the Hardcover API.

        Args:
            query: GraphQL query string
            variables: Optional variables for the query

        Returns:
            Response data as dictionary

        Raises:
            requests.exceptions.RequestException: If the request fails
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = requests.post(self.api_url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Check for GraphQL errors
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                raise Exception(f"GraphQL query failed: {data['errors']}")

            # Add delay to respect rate limiting
            time.sleep(self.request_delay)

            return data

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("Rate limit exceeded. Please wait and try again.")
            raise

    def get_books_by_status(self, status_ids: list[int]) -> list[dict]:
        """
        Fetch books with specified status IDs from the user's library.

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
        query GetBooksByStatus($statusIds: [Int!]!) {
          me {
            user_books(where: {status_id: {_in: $statusIds}}) {
              status_id
              rating
              date_added
              book {
                id
                title
                slug
                subtitle
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

        # Map status IDs to readable names
        status_names = {1: "Want to Read", 2: "Currently Reading", 3: "Read"}
        status_labels = [status_names.get(sid, f"Status {sid}") for sid in status_ids]
        logger.info(f"Fetching books from Hardcover with statuses: {', '.join(status_labels)}")

        try:
            variables = {"statusIds": status_ids}
            response = self._make_request(query, variables)

            # Extract user_books (me is returned as a list with one element)
            me_data = response.get("data", {}).get("me", [])
            if isinstance(me_data, list) and len(me_data) > 0:
                user_books = me_data[0].get("user_books", [])
            elif isinstance(me_data, dict):
                user_books = me_data.get("user_books", [])
            else:
                user_books = []

            books = []
            for user_book in user_books:
                book_data = user_book.get("book", {})

                # Extract authors
                authors = []
                if book_data.get("contributions"):
                    authors = [contrib["author"]["name"] for contrib in book_data["contributions"]]
                elif book_data.get("cached_contributors"):
                    # Fallback to cached contributors (might be a string)
                    authors = [book_data["cached_contributors"]]

                # Extract ISBNs from all editions
                isbn_list = []
                editions = book_data.get("editions", [])
                for edition in editions:
                    if edition.get("isbn_13"):
                        isbn_list.append(edition["isbn_13"])
                    if edition.get("isbn_10"):
                        isbn_list.append(edition["isbn_10"])

                # Extract cover image URL
                image_data = book_data.get("image", {})
                cover_url = image_data.get("url") if image_data else None

                # Extract series information (take first series if multiple)
                book_series_list = book_data.get("book_series", [])
                series_name = None
                series_position = None
                if book_series_list:
                    first_series = book_series_list[0]
                    series_data = first_series.get("series", {})
                    series_name = series_data.get("name") if series_data else None
                    series_position = first_series.get("position")

                book = {
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

                books.append(book)

            logger.info(f"Found {len(books)} books with specified statuses")
            return books

        except Exception as e:
            logger.error(f"Failed to fetch books from Hardcover: {e}")
            raise

    def get_want_to_read_books(self) -> list[dict]:
        """
        Fetch all books in the user's "want to read" list.

        This is a convenience wrapper around get_books_by_status([1]).

        Returns:
            List of book dictionaries with title, author, and ISBN information
        """
        return self.get_books_by_status([1])

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
