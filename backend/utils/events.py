"""Structured event logging for pipeline observability.

Emits single-line, parseable events at INFO level using the canonical
``event=<type> key1=val1 key2=val2 ...`` format. Designed to be additive —
it complements (never replaces) human-readable ``logger.info`` calls and is
intended for log-aggregation pipelines (grep, fluentd, journalctl).
"""

import logging

logger = logging.getLogger(__name__)


def log_event(event_type: str, **fields: object) -> None:
    """Emit a single-line structured log at INFO level.

    Format: ``event=<type> key1=val1 key2=val2 ...``

    Args:
        event_type: Short, lowercase, snake_case event identifier
            (e.g. ``"pipeline_run_started"``, ``"book_grabbed"``).
        **fields: Arbitrary key/value pairs. Values are stringified via
            ``str()``. Keys with whitespace or ``=`` are not validated —
            callers are expected to use simple identifiers.

    Example:
        >>> log_event("book_imported", book_id=42, size_bytes=1024)
        # Emits: event=book_imported book_id=42 size_bytes=1024
    """
    parts = [f"event={event_type}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))
