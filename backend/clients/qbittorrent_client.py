"""
qBittorrent API Client
Handles cookie-based auth and torrent management via the qBittorrent Web API v2.
"""

import logging
import time
from enum import StrEnum
from pathlib import Path

import requests

from backend.clients import ConnectionTestResult, classify_request_error
from backend.constants import QBIT_RETRY_ATTEMPTS, QBIT_TIMEOUT
from backend.errors import FailureReason, PipelineError
from backend.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Session expires after 1 hour by default; re-auth 5 min before to be safe
SESSION_TTL_SECONDS = 55 * 60


class TorrentState(StrEnum):
    """qBittorrent torrent states."""

    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    STALLED_DL = "stalledDL"
    STALLED_UP = "stalledUP"
    PAUSED_DL = "pausedDL"
    PAUSED_UP = "pausedUP"
    ERROR = "error"
    CHECKING_DL = "checkingDL"
    CHECKING_UP = "checkingUP"
    QUEUED_DL = "queuedDL"
    QUEUED_UP = "queuedUP"
    MOVING = "moving"
    MISSING_FILES = "missingFiles"
    UNKNOWN = "unknown"


# States that indicate a torrent has finished downloading
DOWNLOAD_COMPLETE_STATES = {
    TorrentState.UPLOADING,
    TorrentState.STALLED_UP,
    TorrentState.PAUSED_UP,
}


class QBittorrentClient:
    """Client for interacting with the qBittorrent Web API v2."""

    def __init__(self, username: str, password: str, base_url: str = "http://localhost:8080"):
        """
        Initialize the qBittorrent client.

        Args:
            username: qBittorrent Web UI username
            password: qBittorrent Web UI password
            base_url: Base URL of the qBittorrent Web UI
        """
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Referer": self.base_url})
        self._authenticated = False
        self._auth_time: float = 0.0

    def _login(self) -> None:
        """
        Authenticate against the qBittorrent Web API.

        Raises:
            RuntimeError: If authentication fails.
            requests.exceptions.RequestException: On network errors.
        """
        url = f"{self.base_url}/api/v2/auth/login"
        try:
            response = self._session.post(
                url,
                data={"username": self.username, "password": self.password},
                timeout=30,
            )
            # qBittorrent returns 200 with body "Ok." on success, "Fails." on bad credentials,
            # or 403 when IP is banned after too many failures.
            if response.status_code == 403:
                raise RuntimeError("qBittorrent login rejected (HTTP 403). IP may be temporarily banned.")
            response.raise_for_status()

            body = response.text.strip()
            if body == "Fails.":
                raise RuntimeError("qBittorrent login failed: invalid username or password.")

            self._authenticated = True
            self._auth_time = time.monotonic()
            logger.debug("qBittorrent authentication successful")

        except requests.exceptions.RequestException as e:
            logger.error(f"qBittorrent login request failed: {e}")
            self._authenticated = False
            raise

    def _ensure_authenticated(self) -> None:
        """
        Ensure the session is authenticated, re-logging in if needed.

        Called before every API request. Re-auths if:
        - Never authenticated
        - Session older than SESSION_TTL_SECONDS
        """
        elapsed = time.monotonic() - self._auth_time
        if not self._authenticated or elapsed > SESSION_TTL_SECONDS:
            logger.debug("qBittorrent session expired or not started — re-authenticating")
            self._login()

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        retry_on_auth_fail: bool = True,
    ) -> requests.Response:
        """
        Make an authenticated request to the qBittorrent API.

        Automatically re-authenticates once if the session is rejected (403).
        Connection errors (timeout, refused) are retried with exponential backoff.

        Args:
            endpoint: API endpoint path (e.g. '/api/v2/torrents/info')
            method: HTTP method
            params: Optional query parameters
            data: Optional form data for POST requests
            retry_on_auth_fail: Whether to retry after re-auth on 403

        Returns:
            requests.Response object

        Raises:
            PipelineError: On connection exhaustion or auth failure after re-auth
            requests.exceptions.RequestException: On other HTTP errors
        """
        # Wrap the actual request logic with retry_with_backoff for connection errors
        @retry_with_backoff(
            attempts=QBIT_RETRY_ATTEMPTS,
            exceptions=(requests.exceptions.ConnectionError, requests.exceptions.Timeout),
            failure_reason=FailureReason.QBIT_UNREACHABLE,
        )
        def _do_request() -> requests.Response:
            self._ensure_authenticated()
            url = f"{self.base_url}{endpoint}"

            response = self._session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                timeout=QBIT_TIMEOUT,
            )

            # 403 often means the session cookie expired mid-session — retry once
            if response.status_code == 403 and retry_on_auth_fail:
                logger.debug("qBittorrent returned 403 — session may have expired, re-authenticating")
                self._authenticated = False
                self._ensure_authenticated()
                response = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    timeout=QBIT_TIMEOUT,
                )

            # 401 after re-auth attempt means credentials are invalid
            if response.status_code == 401:
                raise PipelineError(
                    "qBittorrent returned 401 after re-authentication attempt",
                    FailureReason.QBIT_AUTH_FAILED,
                )

            response.raise_for_status()
            return response

        try:
            return _do_request()
        except PipelineError:
            # Re-raise PipelineError as-is (already has proper failure reason)
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"qBittorrent API request failed [{method} {endpoint}]: {e}")
            raise

    def add_torrent(
        self,
        torrent_url: str,
        save_path: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """
        Add a torrent by magnet link or URL.

        Args:
            torrent_url: Magnet link or HTTP torrent URL
            save_path: Optional download directory override
            category: Optional category label
            tags: Optional list of tags

        Returns:
            True if added successfully, False otherwise
        """
        try:
            data: dict = {"urls": torrent_url}
            if save_path:
                data["savepath"] = save_path
            if category:
                data["category"] = category
            if tags:
                data["tags"] = ",".join(tags)

            response = self._make_request("/api/v2/torrents/add", method="POST", data=data)
            success = response.text.strip() == "Ok."
            if success:
                logger.info(f"Torrent added successfully: {torrent_url[:80]}")
            else:
                logger.warning(f"Unexpected response when adding torrent: {response.text!r}")
            return success

        except Exception as e:
            logger.error(f"Error adding torrent: {e}")
            return False

    def get_torrents(
        self,
        filter: str | None = None,
        category: str | None = None,
        hashes: list[str] | None = None,
    ) -> list[dict]:
        """
        Get a list of torrents.

        Args:
            filter: Optional state filter (e.g. 'downloading', 'completed')
            category: Optional category filter
            hashes: Optional list of torrent hashes to retrieve

        Returns:
            List of torrent info dictionaries
        """
        try:
            params: dict = {}
            if filter:
                params["filter"] = filter
            if category:
                params["category"] = category
            if hashes:
                params["hashes"] = "|".join(hashes)

            response = self._make_request("/api/v2/torrents/info", params=params)
            return response.json()

        except Exception as e:
            logger.error(f"Error getting torrents: {e}")
            return []

    def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        """
        Get the file list for a specific torrent.

        Args:
            torrent_hash: Torrent info hash

        Returns:
            List of file info dictionaries with name, size, priority, progress
        """
        try:
            response = self._make_request("/api/v2/torrents/files", params={"hash": torrent_hash})
            return response.json()

        except Exception as e:
            logger.error(f"Error getting torrent files for {torrent_hash}: {e}")
            return []

    def get_torrent_properties(self, torrent_hash: str) -> dict | None:
        """
        Get detailed properties for a specific torrent.

        Args:
            torrent_hash: Torrent info hash

        Returns:
            Torrent properties dictionary, or None if not found
        """
        try:
            response = self._make_request("/api/v2/torrents/properties", params={"hash": torrent_hash})
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.debug(f"Torrent not found: {torrent_hash}")
                return None
            logger.error(f"Error getting torrent properties for {torrent_hash}: {e}")
            return None

        except Exception as e:
            logger.error(f"Error getting torrent properties for {torrent_hash}: {e}")
            return None

    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int) -> bool:
        """
        Set download priority for specific files in a torrent.

        Priority values:
            0 = Do not download
            1 = Normal priority
            6 = High priority
            7 = Maximum priority

        Args:
            torrent_hash: Torrent info hash
            file_ids: List of file indices (0-based, from get_torrent_files)
            priority: Priority value (0, 1, 6, or 7)

        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                "hash": torrent_hash,
                "id": "|".join(str(i) for i in file_ids),
                "priority": priority,
            }
            self._make_request("/api/v2/torrents/filePrio", method="POST", data=data)
            logger.debug(f"Set priority {priority} for {len(file_ids)} file(s) in {torrent_hash}")
            return True

        except Exception as e:
            logger.error(f"Error setting file priority for {torrent_hash}: {e}")
            return False

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """
        Delete a torrent, optionally including downloaded files.

        Args:
            torrent_hash: Torrent info hash
            delete_files: If True, also delete the downloaded files from disk

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            data = {
                "hashes": torrent_hash,
                "deleteFiles": "true" if delete_files else "false",
            }
            self._make_request("/api/v2/torrents/delete", method="POST", data=data)
            logger.info(f"Deleted torrent {torrent_hash} (delete_files={delete_files})")
            return True

        except Exception as e:
            logger.error(f"Error deleting torrent {torrent_hash}: {e}")
            return False

    def ensure_category_exists(self, category: str, save_path: str = "") -> bool:
        """
        Create a torrent category if it does not already exist.

        Ignores 409 Conflict, which means the category already exists.

        Args:
            category: Category name to create
            save_path: Default save path for this category

        Returns:
            True if the category exists (created or already existed), False on error
        """
        try:
            data = {"category": category, "savePath": save_path}
            self._make_request("/api/v2/torrents/createCategory", method="POST", data=data)
            logger.debug(f"Created qBittorrent category: {category!r}")
            return True

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 409:
                logger.debug(f"Category already exists: {category!r}")
                return True
            logger.error(f"Error creating category {category!r}: {e}")
            return False

        except Exception as e:
            logger.error(f"Error creating category {category!r}: {e}")
            return False

    def test_connection(self) -> ConnectionTestResult:
        """
        Test the connection and authentication to qBittorrent.

        Returns:
            ConnectionTestResult with success status and error details
        """
        try:
            self._authenticated = False
            self._login()

            response = self._make_request("/api/v2/app/version")
            version = response.text.strip()
            logger.info(f"Successfully connected to qBittorrent (version: {version})")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to qBittorrent (v{version})",
            )

        except RuntimeError as e:
            # Login failures surface as RuntimeError
            logger.error(f"qBittorrent connection test failed: {e}")
            return ConnectionTestResult(
                success=False,
                error=str(e),
                error_type="auth_failed",
            )

        except requests.exceptions.HTTPError as e:
            logger.error(f"qBittorrent connection test failed: {e}")
            result = classify_request_error(e, "qBittorrent")
            return result

        except Exception as e:
            logger.error(f"qBittorrent connection test failed: {e}")
            return classify_request_error(e, "qBittorrent")

    def get_completed_file_path(self, torrent_hash: str) -> Path | None:
        """
        Get the filesystem path of the first EPUB file in a completed torrent.

        Checks torrent state first — returns None if not yet completed.
        For multi-file torrents, returns the first file with an .epub extension.
        For single-file torrents, returns the content path directly.

        Args:
            torrent_hash: Torrent info hash

        Returns:
            Path to the EPUB file, or None if not completed / no EPUB found
        """
        try:
            torrents = self.get_torrents(hashes=[torrent_hash])
            if not torrents:
                logger.debug(f"Torrent not found: {torrent_hash}")
                return None

            torrent = torrents[0]
            state = torrent.get("state", "")
            progress = torrent.get("progress", 0.0)

            is_complete = state in DOWNLOAD_COMPLETE_STATES or progress >= 1.0
            if not is_complete:
                logger.debug(f"Torrent {torrent_hash} not yet complete (state={state}, progress={progress:.1%})")
                return None

            content_path = torrent.get("content_path", "")
            if content_path and content_path.lower().endswith(".epub"):
                return Path(content_path)

            files = self.get_torrent_files(torrent_hash)
            save_path = torrent.get("save_path", "")

            for file_info in files:
                name = file_info.get("name", "")
                if name.lower().endswith(".epub"):
                    full_path = Path(save_path) / name
                    logger.debug(f"Found EPUB in torrent {torrent_hash}: {full_path}")
                    return full_path

            logger.warning(f"No EPUB file found in torrent {torrent_hash}")
            return None

        except Exception as e:
            logger.error(f"Error getting completed file path for {torrent_hash}: {e}")
            return None
