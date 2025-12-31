"""
Readarr API Client
Handles REST API queries to search for books and retrieve file paths.
"""

import logging

import requests
from fuzzywuzzy import fuzz

from backend.clients import ConnectionTestResult, classify_request_error

logger = logging.getLogger(__name__)


class ReadarrClient:
    """Client for interacting with the Readarr REST API."""

    def __init__(self, api_key: str, base_url: str = "http://localhost:8787"):
        """
        Initialize the Readarr client.

        Args:
            api_key: Readarr API key from Settings → General → Security
            base_url: Base URL of the Readarr instance
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}

    def _make_request(
        self, endpoint: str, params: dict | None = None, method: str = "GET", json_data: dict | None = None
    ) -> dict:
        """
        Make a request to the Readarr API.

        Args:
            endpoint: API endpoint (e.g., '/api/v1/book')
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
            logger.error(f"Readarr API request failed: {e}")
            raise

    def search_by_isbn(self, isbn: str) -> dict | None:
        """
        Search for a book by ISBN.

        Args:
            isbn: ISBN-10 or ISBN-13

        Returns:
            Book data if found, None otherwise
        """
        try:
            results = self._make_request("/api/v1/book/lookup", params={"term": f"isbn:{isbn}"})

            if results and isinstance(results, list) and len(results) > 0:
                logger.debug(f"Found book by ISBN {isbn}: {results[0].get('title')}")
                return results[0]
            else:
                logger.debug(f"No book found for ISBN: {isbn}")
                return None

        except Exception as e:
            logger.error(f"Error searching for ISBN {isbn}: {e}")
            return None

    def search_by_title_author(self, title: str, author: str = "", fuzzy_threshold: int = 80) -> dict | None:
        """
        Search for a book by title and author using fuzzy matching.

        Args:
            title: Book title
            author: Author name (optional)
            fuzzy_threshold: Minimum similarity score (0-100) for matching

        Returns:
            Best matching book data if found, None otherwise
        """
        search_term = f"{title} {author}".strip()

        try:
            results = self._make_request("/api/v1/book/lookup", params={"term": search_term})

            if not results or not isinstance(results, list):
                logger.debug(f"No results found for: {search_term}")
                return None

            # Find the best match using fuzzy string matching
            best_match = None
            best_score = 0

            for book in results:
                book_title = book.get("title", "")
                book_author = book.get("authorTitle", "")

                # Calculate similarity scores
                title_score = fuzz.ratio(title.lower(), book_title.lower())
                author_score = fuzz.ratio(author.lower(), book_author.lower()) if author else 100

                # Weighted average (title is more important)
                combined_score = (title_score * 0.7) + (author_score * 0.3)

                logger.debug(
                    f"Match candidate: '{book_title}' by {book_author} "
                    f"(title: {title_score}%, author: {author_score}%, combined: {combined_score:.1f}%)"
                )

                if combined_score > best_score and combined_score >= fuzzy_threshold:
                    best_score = combined_score
                    best_match = book

            if best_match:
                logger.info(
                    f"Found fuzzy match for '{title}': '{best_match.get('title')}' (confidence: {best_score:.1f}%)"
                )
                return best_match
            else:
                logger.debug(f"No match found above threshold ({fuzzy_threshold}%) for: {search_term}")
                return None

        except Exception as e:
            logger.error(f"Error searching for '{search_term}': {e}")
            return None

    def get_book_files(self, book_id: int, format_filter: str = "epub") -> list[dict]:
        """
        Get file paths for a specific book.

        Args:
            book_id: Readarr book ID
            format_filter: File format to filter (e.g., 'epub', 'mobi')

        Returns:
            List of book file dictionaries with path information
        """
        try:
            results = self._make_request("/api/v1/bookfile", params={"bookId": book_id})

            if not results or not isinstance(results, list):
                logger.debug(f"No files found for book ID: {book_id}")
                return []

            # Filter by format
            format_filter_lower = format_filter.lower()
            filtered_files = []

            for file_data in results:
                file_path = file_data.get("path", "")
                quality_name = file_data.get("quality", {}).get("quality", {}).get("name", "").lower()

                # Check if file matches the desired format
                if file_path.lower().endswith(f".{format_filter_lower}") or quality_name == format_filter_lower:
                    filtered_files.append(file_data)
                    logger.debug(f"Found {format_filter.upper()} file: {file_path}")

            return filtered_files

        except Exception as e:
            logger.error(f"Error getting files for book ID {book_id}: {e}")
            return []

    def get_root_folders(self) -> list[dict]:
        """
        Get available root folders from Readarr.

        Returns:
            List of root folder dictionaries with path and ID information
        """
        try:
            results = self._make_request("/api/v1/rootfolder")

            if not results or not isinstance(results, list):
                logger.warning("No root folders found in Readarr")
                return []

            logger.debug(f"Found {len(results)} root folder(s)")
            return results

        except Exception as e:
            logger.error(f"Error getting root folders: {e}")
            return []

    def get_quality_profiles(self) -> list[dict]:
        """
        Get available quality profiles from Readarr.

        Returns:
            List of quality profile dictionaries
        """
        try:
            results = self._make_request("/api/v1/qualityprofile")

            if not results or not isinstance(results, list):
                logger.warning("No quality profiles found in Readarr")
                return []

            logger.debug(f"Found {len(results)} quality profile(s)")
            return results

        except Exception as e:
            logger.error(f"Error getting quality profiles: {e}")
            return []

    def get_metadata_profiles(self) -> list[dict]:
        """
        Get available metadata profiles from Readarr.

        Returns:
            List of metadata profile dictionaries
        """
        try:
            results = self._make_request("/api/v1/metadataprofile")

            if not results or not isinstance(results, list):
                logger.warning("No metadata profiles found in Readarr")
                return []

            logger.debug(f"Found {len(results)} metadata profile(s)")
            return results

        except Exception as e:
            logger.error(f"Error getting metadata profiles: {e}")
            return []

    def lookup_author(self, author_name: str) -> dict | None:
        """
        Look up an author by name from the metadata provider.

        Args:
            author_name: Author name to search for

        Returns:
            Author metadata if found, None otherwise
        """
        try:
            results = self._make_request("/api/v1/author/lookup", params={"term": author_name})

            if results and isinstance(results, list) and len(results) > 0:
                logger.debug(f"Found author metadata for: {author_name}")
                return results[0]
            else:
                logger.debug(f"No author metadata found for: {author_name}")
                return None

        except Exception as e:
            logger.error(f"Error looking up author '{author_name}': {e}")
            return None

    def get_author_by_foreign_id(self, foreign_author_id: str) -> dict | None:
        """
        Get an author by their foreign ID (e.g., Goodreads ID).

        Args:
            foreign_author_id: The foreign author ID (e.g., from Goodreads)

        Returns:
            Author data if found, None otherwise
        """
        try:
            results = self._make_request("/api/v1/author")

            if not results or not isinstance(results, list):
                return None

            for author in results:
                if author.get("foreignAuthorId") == foreign_author_id:
                    logger.debug(f"Found existing author: {author.get('authorName')}")
                    return author

            return None

        except Exception as e:
            logger.error(f"Error getting author by foreign ID {foreign_author_id}: {e}")
            return None

    def add_author(
        self, author_data: dict, quality_profile_id: int, metadata_profile_id: int, root_folder_path: str
    ) -> dict | None:
        """
        Add an author to Readarr.

        Args:
            author_data: Author metadata from lookup (must include foreignAuthorId)
            quality_profile_id: Quality profile ID to use
            metadata_profile_id: Metadata profile ID to use
            root_folder_path: Root folder path for author's books

        Returns:
            Added author data if successful, None otherwise
        """
        try:
            foreign_author_id = author_data.get("foreignAuthorId")
            author_name = author_data.get("authorName") or author_data.get("authorTitle")

            if not foreign_author_id:
                logger.error(f"Cannot add author '{author_name}': missing foreignAuthorId")
                return None

            # Check if author already exists
            existing_author = self.get_author_by_foreign_id(foreign_author_id)
            if existing_author:
                logger.debug(f"Author '{author_name}' already exists in Readarr")
                return existing_author

            # Prepare author payload
            author_payload = {
                "foreignAuthorId": foreign_author_id,
                "authorName": author_name,
                "qualityProfileId": quality_profile_id,
                "metadataProfileId": metadata_profile_id,
                "rootFolderPath": root_folder_path,
                "monitored": True,
                "addOptions": {"monitor": "all", "searchForMissingBooks": False},
            }

            # Add any additional fields from the lookup data
            if "titleSlug" in author_data:
                author_payload["titleSlug"] = author_data["titleSlug"]
            if "images" in author_data:
                author_payload["images"] = author_data["images"]
            if "links" in author_data:
                author_payload["links"] = author_data["links"]

            result = self._make_request("/api/v1/author", method="POST", json_data=author_payload)

            if result:
                logger.info(f"Successfully added author to Readarr: {author_name}")
                return result
            else:
                logger.error(f"Failed to add author: {author_name}")
                return None

        except Exception as e:
            logger.error(f"Error adding author '{author_data.get('authorName', 'unknown')}': {e}")
            return None

    def add_book_to_library(
        self,
        book_metadata: dict,
        quality_profile_id: int,
        metadata_profile_id: int,
        root_folder_path: str,
        search: bool = True,
    ) -> dict | None:
        """
        Add a book to Readarr library.

        Args:
            book_metadata: Book metadata from lookup (must include foreignBookId and author data)
            quality_profile_id: Quality profile ID to use
            metadata_profile_id: Metadata profile ID to use
            root_folder_path: Root folder path for books
            search: Whether to trigger automatic search after adding

        Returns:
            Added book data if successful, None otherwise
        """
        try:
            foreign_book_id = book_metadata.get("foreignBookId")
            title = book_metadata.get("title")
            author_metadata = book_metadata.get("author")

            if not foreign_book_id:
                logger.error(f"Cannot add book '{title}': missing foreignBookId")
                return None

            if not author_metadata:
                logger.error(f"Cannot add book '{title}': missing author metadata")
                return None

            # First, ensure the author exists in Readarr
            author = self.add_author(author_metadata, quality_profile_id, metadata_profile_id, root_folder_path)
            if not author:
                logger.error(f"Failed to add/find author for book: {title}")
                return None

            author_id = author.get("id")
            if not author_id:
                logger.error(f"Author data missing ID for book: {title}")
                return None

            # Check if book already exists
            existing_books = self._make_request("/api/v1/book")
            if existing_books and isinstance(existing_books, list):
                for book in existing_books:
                    if book.get("foreignBookId") == foreign_book_id:
                        logger.info(f"Book '{title}' already exists in Readarr")
                        return book

            # Prepare book payload
            book_payload = {
                "foreignBookId": foreign_book_id,
                "title": title,
                "authorId": author_id,
                "monitored": True,
                "qualityProfileId": quality_profile_id,
                "metadataProfileId": metadata_profile_id,
                "addOptions": {"searchForNewBook": search},
            }

            # Add optional fields from metadata
            if "titleSlug" in book_metadata:
                book_payload["titleSlug"] = book_metadata["titleSlug"]
            if "images" in book_metadata:
                book_payload["images"] = book_metadata["images"]
            if "links" in book_metadata:
                book_payload["links"] = book_metadata["links"]
            if "isbn13" in book_metadata:
                book_payload["isbn13"] = book_metadata["isbn13"]
            if "asin" in book_metadata:
                book_payload["asin"] = book_metadata["asin"]
            if "releaseDate" in book_metadata:
                book_payload["releaseDate"] = book_metadata["releaseDate"]
            if "ratings" in book_metadata:
                book_payload["ratings"] = book_metadata["ratings"]

            result = self._make_request("/api/v1/book", method="POST", json_data=book_payload)

            if result:
                logger.info(f"Successfully added book to Readarr: {title}")
                return result
            else:
                logger.error(f"Failed to add book: {title}")
                return None

        except Exception as e:
            logger.error(f"Error adding book '{book_metadata.get('title', 'unknown')}': {e}")
            return None

    def trigger_book_search(self, book_id: int) -> bool:
        """
        Trigger a search for a specific book.

        Args:
            book_id: Readarr book ID

        Returns:
            True if search was triggered successfully, False otherwise
        """
        try:
            command_payload = {"name": "BookSearch", "bookIds": [book_id]}

            result = self._make_request("/api/v1/command", method="POST", json_data=command_payload)

            if result:
                logger.info(f"Triggered search for book ID: {book_id}")
                return True
            else:
                logger.error(f"Failed to trigger search for book ID: {book_id}")
                return False

        except Exception as e:
            logger.error(f"Error triggering search for book ID {book_id}: {e}")
            return False

    def find_book_and_files(
        self,
        title: str,
        author: str = "",
        isbns: list[str] = None,
        format_filter: str = "epub",
        fuzzy_threshold: int = 80,
        return_metadata_only: bool = False,
    ) -> dict | None:
        """
        Find a book and its files using ISBN first, then fuzzy matching.

        Args:
            title: Book title
            author: Author name
            isbns: List of ISBNs to try
            format_filter: File format to filter
            fuzzy_threshold: Minimum similarity score for fuzzy matching
            return_metadata_only: If True, return metadata even if no files found

        Returns:
            Dictionary with book data, file paths, and has_files flag
            Returns None only if book metadata cannot be found
        """
        book_data = None

        # Try ISBN matching first
        if isbns:
            for isbn in isbns:
                book_data = self.search_by_isbn(isbn)
                if book_data:
                    logger.info(f"Matched '{title}' by ISBN: {isbn}")
                    break

        # Fallback to fuzzy title/author matching
        if not book_data:
            logger.debug(f"No ISBN match, trying fuzzy search for: {title}")
            book_data = self.search_by_title_author(title, author, fuzzy_threshold)

        # If we found a book, get its files
        if book_data:
            book_id = book_data.get("id")
            has_files = False
            files = []

            if book_id:
                files = self.get_book_files(book_id, format_filter)
                has_files = len(files) > 0

            if has_files:
                return {"book": book_data, "files": files, "has_files": True}
            elif return_metadata_only:
                # Return metadata even without files (useful for auto-add feature)
                return {"book": book_data, "files": [], "has_files": False}
            else:
                logger.warning(f"Book found but no {format_filter.upper()} files available: {title}")
                return None

        return None

    def test_connection(self) -> ConnectionTestResult:
        """
        Test the connection to Readarr API.

        Returns:
            ConnectionTestResult with success status and error details
        """
        try:
            response = self._make_request("/api/v1/system/status")

            if response:
                version = response.get("version", "unknown")
                logger.info(f"Successfully connected to Readarr (version: {version})")
                return ConnectionTestResult(
                    success=True,
                    message=f"Connected to Readarr (v{version})",
                )
            else:
                logger.error("Could not retrieve system status from Readarr")
                return ConnectionTestResult(
                    success=False,
                    error="Could not retrieve system status from Readarr",
                    error_type="invalid_response",
                )

        except requests.exceptions.HTTPError as e:
            logger.error(f"Readarr connection test failed: {e}")
            result = classify_request_error(e, "Readarr")
            # Add Readarr-specific guidance for auth errors
            if result.get("error_type") == "auth_failed":
                result["error"] = "Readarr API key is invalid. Check Settings > General in Readarr."
            return result

        except Exception as e:
            logger.error(f"Readarr connection test failed: {e}")
            return classify_request_error(e, "Readarr")
