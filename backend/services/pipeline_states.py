"""
Pipeline state machine for book and download status transitions with validation.
"""

from backend.models.book import BookStatus, DownloadStatus

# Valid state transitions for books
VALID_BOOK_TRANSITIONS = {
    BookStatus.MISSING: {BookStatus.SEARCHING, BookStatus.FAILED},
    BookStatus.WANTED: {BookStatus.SEARCHING, BookStatus.FAILED, BookStatus.MISSING},
    BookStatus.SEARCHING: {BookStatus.GRABBED, BookStatus.FAILED, BookStatus.WANTED},
    BookStatus.GRABBED: {BookStatus.DOWNLOADING, BookStatus.FAILED, BookStatus.SEARCHING},
    BookStatus.DOWNLOADING: {BookStatus.IMPORTING, BookStatus.FAILED, BookStatus.GRABBED},
    BookStatus.IMPORTING: {BookStatus.IN_LIBRARY, BookStatus.FAILED},
    BookStatus.IN_LIBRARY: set(),  # Terminal state
    BookStatus.FAILED: {BookStatus.WANTED, BookStatus.MISSING, BookStatus.SEARCHING},  # Can retry
}

# Valid state transitions for downloads
VALID_DOWNLOAD_TRANSITIONS = {
    DownloadStatus.QUEUED: {DownloadStatus.DOWNLOADING, DownloadStatus.FAILED},
    DownloadStatus.DOWNLOADING: {DownloadStatus.COMPLETED, DownloadStatus.FAILED},
    DownloadStatus.COMPLETED: {DownloadStatus.IMPORTING, DownloadStatus.FAILED},
    DownloadStatus.IMPORTING: {DownloadStatus.IMPORTED, DownloadStatus.FAILED},
    DownloadStatus.IMPORTED: set(),  # Terminal state
    DownloadStatus.FAILED: {DownloadStatus.QUEUED},  # Can retry
}


def can_transition(current_status: str, target_status: str, is_download: bool = False) -> bool:
    """
    Check if a state transition is valid.

    Args:
        current_status: Current status value
        target_status: Target status value
        is_download: If True, validate against download transitions; else book transitions

    Returns:
        True if transition is valid, False otherwise
    """
    if is_download:
        try:
            current = DownloadStatus(current_status)
            target = DownloadStatus(target_status)
        except ValueError:
            return False

        return target in VALID_DOWNLOAD_TRANSITIONS.get(current, set())

    try:
        current = BookStatus(current_status)
        target = BookStatus(target_status)
    except ValueError:
        return False

    return target in VALID_BOOK_TRANSITIONS.get(current, set())


def transition_book(book, target_status: str) -> bool:
    """
    Transition a book to a new status if valid.

    Args:
        book: Book model instance
        target_status: Target BookStatus value

    Returns:
        True if transition succeeded, False if invalid
    """
    if not can_transition(book.status, target_status, is_download=False):
        return False

    book.status = target_status
    return True


def transition_download(download, target_status: str) -> bool:
    """
    Transition a download to a new status if valid.

    Args:
        download: Download model instance
        target_status: Target DownloadStatus value

    Returns:
        True if transition succeeded, False if invalid
    """
    if not can_transition(download.status, target_status, is_download=True):
        return False

    download.status = target_status
    return True


def get_actionable_books(books, target_status: str | None = None) -> list:
    """
    Filter books that can transition to a target status.

    Args:
        books: List of Book model instances
        target_status: Target BookStatus value (if None, return all non-terminal books)

    Returns:
        List of books that can transition to target_status
    """
    if target_status is None:
        # Return all books not in terminal states
        return [b for b in books if b.status != BookStatus.IN_LIBRARY.value]

    actionable = []
    for book in books:
        if can_transition(book.status, target_status, is_download=False):
            actionable.append(book)

    return actionable


def get_actionable_downloads(downloads, target_status: str | None = None) -> list:
    """
    Filter downloads that can transition to a target status.

    Args:
        downloads: List of Download model instances
        target_status: Target DownloadStatus value (if None, return all non-terminal downloads)

    Returns:
        List of downloads that can transition to target_status
    """
    if target_status is None:
        # Return all downloads not in terminal states
        return [d for d in downloads if d.status != DownloadStatus.IMPORTED.value]

    actionable = []
    for download in downloads:
        if can_transition(download.status, target_status, is_download=True):
            actionable.append(download)

    return actionable
