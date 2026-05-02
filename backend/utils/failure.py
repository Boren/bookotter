# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
"""Failure history helpers for ``Book.failure_history`` (ring buffer)."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models.book import Book

FAILURE_HISTORY_MAX = 5


def _append_failure_history(book: "Book", reason: str) -> None:
    """Append a failure entry to ``book.failure_history`` (last ``FAILURE_HISTORY_MAX``).

    Callers must pass the OLD ``book.failure_reason`` when clearing/retrying,
    or the NEW reason when transitioning into a failure state.
    """
    history = list(book.failure_history or [])
    history.append(
        {
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
            "attempt": book.retry_count,
        }
    )
    book.failure_history = history[-FAILURE_HISTORY_MAX:]
