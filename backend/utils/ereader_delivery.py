"""Shared E-reader delivery bookkeeping helpers."""

from backend.models.book import Book, EreaderDeliveryStatus
from backend.utils.clock import naive_utcnow


def rearm_ereader_delivery(book: Book, real_ereader: dict | None, ereader_shelves: set[str]) -> bool:
    """Re-queue a DELIVERED mirror-set book after its local file changed.

    Mirrors the pipeline's auto-delivery gate: only books on a synced shelf or
    pinned re-send, and only when a real E-reader is configured. Returns True if
    the book was re-armed.
    """
    if (
        book.ereader_delivery_status == EreaderDeliveryStatus.DELIVERED.value
        and real_ereader is not None
        and (book.hardcover_status in ereader_shelves or book.ereader_pinned)
    ):
        book.ereader_delivery_status = EreaderDeliveryStatus.PENDING.value
        book.ereader_first_pending_at = naive_utcnow()
        book.ereader_delivery_attempts = 0
        return True
    return False
