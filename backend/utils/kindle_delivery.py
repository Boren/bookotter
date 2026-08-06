"""Shared Kindle delivery bookkeeping helpers."""

from backend.models.book import Book, KindleDeliveryStatus
from backend.utils.clock import naive_utcnow


def rearm_kindle_delivery(book: Book, real_kindle: dict | None, kindle_shelves: set[str]) -> bool:
    """Re-queue a DELIVERED mirror-set book after its local file changed.

    Mirrors the pipeline's auto-delivery gate: only books on a synced shelf or
    pinned re-send, and only when a real Kindle is configured. Returns True if
    the book was re-armed.
    """
    if (
        book.kindle_delivery_status == KindleDeliveryStatus.DELIVERED.value
        and real_kindle is not None
        and (book.hardcover_status in kindle_shelves or book.kindle_pinned)
    ):
        book.kindle_delivery_status = KindleDeliveryStatus.PENDING.value
        book.kindle_first_pending_at = naive_utcnow()
        book.kindle_delivery_attempts = 0
        return True
    return False
