# API clients package

from typing import TypedDict

import requests


class ConnectionTestResult(TypedDict, total=False):
    """Structured result for connection tests."""

    success: bool
    message: str | None
    error: str | None
    error_type: str | None


def classify_request_error(
    e: Exception,
    service_name: str = "API",
) -> ConnectionTestResult:
    """
    Classify a requests exception into a user-friendly error result.

    Maps HTTP status codes and exception types to actionable messages:
    - 401/403: Authentication failed
    - 404: Endpoint not found
    - 429: Rate limited
    - 5xx: Server error
    - ConnectionError: Network/DNS issues
    - Timeout: Connection timed out

    Args:
        e: The exception to classify
        service_name: Name of the service for error messages

    Returns:
        ConnectionTestResult with error details
    """
    # Handle HTTP errors with status codes
    if isinstance(e, requests.exceptions.HTTPError):
        status_code = e.response.status_code if e.response is not None else None

        if status_code == 401:
            return ConnectionTestResult(
                success=False,
                error="Authentication failed (HTTP 401). The API key/token is invalid.",
                error_type="auth_failed",
            )
        elif status_code == 403:
            return ConnectionTestResult(
                success=False,
                error="Access denied (HTTP 403). The API key/token doesn't have permission.",
                error_type="auth_failed",
            )
        elif status_code == 404:
            return ConnectionTestResult(
                success=False,
                error=f"Endpoint not found (HTTP 404). Check the {service_name} URL.",
                error_type="not_found",
            )
        elif status_code == 429:
            return ConnectionTestResult(
                success=False,
                error="Rate limit exceeded (HTTP 429). Wait a moment and try again.",
                error_type="rate_limited",
            )
        elif status_code and 500 <= status_code < 600:
            return ConnectionTestResult(
                success=False,
                error=f"Server error (HTTP {status_code}). {service_name} may be experiencing issues.",
                error_type="server_error",
            )
        else:
            return ConnectionTestResult(
                success=False,
                error=f"HTTP error {status_code}: {e}",
                error_type="http_error",
            )

    # Handle connection errors (network/DNS issues)
    if isinstance(e, requests.exceptions.ConnectionError):
        # Extract more specific info from the error
        error_str = str(e).lower()
        if "name or service not known" in error_str or "nodename nor servname" in error_str:
            return ConnectionTestResult(
                success=False,
                error=f"Could not resolve hostname. Check the {service_name} URL.",
                error_type="network_error",
            )
        elif "connection refused" in error_str:
            return ConnectionTestResult(
                success=False,
                error=f"Connection refused. Is {service_name} running?",
                error_type="network_error",
            )
        else:
            return ConnectionTestResult(
                success=False,
                error=f"Could not connect to {service_name}. Check the URL and network.",
                error_type="network_error",
            )

    # Handle timeout
    if isinstance(e, requests.exceptions.Timeout):
        return ConnectionTestResult(
            success=False,
            error=f"Connection timed out. {service_name} may be slow or unreachable.",
            error_type="timeout",
        )

    # Handle other request exceptions
    if isinstance(e, requests.exceptions.RequestException):
        return ConnectionTestResult(
            success=False,
            error=f"{service_name} request failed: {e}",
            error_type="request_error",
        )

    # Fallback for unknown exceptions
    return ConnectionTestResult(
        success=False,
        error=str(e),
        error_type="unknown",
    )


def classify_ssh_error(e: Exception, hostname: str = "") -> ConnectionTestResult:
    """
    Classify an SSH/Paramiko exception into a user-friendly error result.

    Args:
        e: The exception to classify
        hostname: The hostname for error messages

    Returns:
        ConnectionTestResult with error details
    """
    error_str = str(e).lower()
    host_info = f" ({hostname})" if hostname else ""

    # Authentication failures
    if "authentication failed" in error_str or "auth failed" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"SSH authentication failed{host_info}. Check username/password or SSH key.",
            error_type="auth_failed",
        )

    # Permission denied
    if "permission denied" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"SSH permission denied{host_info}. Check credentials.",
            error_type="auth_failed",
        )

    # Host not reachable
    if "no route to host" in error_str or "network is unreachable" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"Cannot reach Kindle{host_info}. Is it powered on and connected?",
            error_type="network_error",
        )

    # Connection refused
    if "connection refused" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"Connection refused{host_info}. SSH may not be enabled on the Kindle.",
            error_type="network_error",
        )

    # DNS/hostname issues
    if "name or service not known" in error_str or "nodename nor servname" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"Could not resolve hostname{host_info}. Check the Kindle hostname.",
            error_type="network_error",
        )

    # Timeout
    if "timed out" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"Connection timed out{host_info}. Kindle may be slow or unreachable.",
            error_type="timeout",
        )

    # Host key issues
    if "host key" in error_str:
        return ConnectionTestResult(
            success=False,
            error=f"SSH host key verification failed{host_info}.",
            error_type="host_key_error",
        )

    # Fallback
    return ConnectionTestResult(
        success=False,
        error=f"SSH connection failed{host_info}: {e}",
        error_type="unknown",
    )
