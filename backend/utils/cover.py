"""
Cover image fetch utility.

Fetches cover images from URLs with size and content-type validation.
Returns (image_bytes, content_type) on success, None on any failure.
"""

import logging

import requests

logger = logging.getLogger(__name__)

MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def fetch_cover(url: str | None, timeout: float = 10.0) -> tuple[bytes, str] | None:
    """
    Fetch a cover image from a URL with validation.

    Args:
        url: Image URL to fetch. None or empty string returns None without logging.
        timeout: Request timeout in seconds (default: 10.0).

    Returns:
        Tuple of (image_bytes, content_type) on success, None on any failure.
        Never raises exceptions — all errors return None.

    Validation:
        - Content-Type must start with "image/" (case-insensitive)
        - Content-Length header (if present) must not exceed 10 MB
        - Streamed body must not exceed 10 MB cap
        - Network errors, timeouts, and non-2xx status codes return None
    """
    # Handle None or empty URL without logging
    if not url:
        return None

    try:
        response = requests.get(
            url,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to fetch cover from %s: %s", url, exc)
        return None

    # Check HTTP status code
    if response.status_code != 200:
        logger.warning(
            "Cover fetch returned non-2xx status %d for URL: %s",
            response.status_code,
            url,
        )
        return None

    # Validate Content-Type header
    content_type = response.headers.get("Content-Type", "").lower()
    if not content_type.startswith("image/"):
        logger.warning("Non-image content type: %s for URL: %s", content_type, url)
        return None

    # Check Content-Length header before reading
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            content_length_int = int(content_length)
            if content_length_int > MAX_SIZE:
                logger.warning(
                    "Cover image too large (%d bytes) for URL: %s",
                    content_length_int,
                    url,
                )
                return None
        except ValueError:
            # Invalid Content-Length header, proceed with streaming
            pass

    # Stream the body with size cap enforcement
    chunks = []
    total_size = 0

    try:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:  # Skip keep-alive chunks
                total_size += len(chunk)
                if total_size > MAX_SIZE:
                    logger.warning(
                        "Cover image exceeds 10MB cap for URL: %s",
                        url,
                    )
                    return None
                chunks.append(chunk)
    except requests.exceptions.RequestException as exc:
        logger.warning("Error streaming cover from %s: %s", url, exc)
        return None

    image_bytes = b"".join(chunks)
    return (image_bytes, content_type)
