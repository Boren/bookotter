"""
Pipeline constants — retry/timeout/threshold values.

By design, these are CODE CONSTANTS (not config.yaml fields).
All retry/timeout/threshold values live here; importing services use these.
Wave 1+ tasks will reference these constants instead of hardcoded values.
"""

from typing import Final

# ─── Hardcover API ─────────────────────────────────────────────────────────────
HARDCOVER_RETRY_ATTEMPTS: Final[int] = 3
HARDCOVER_TIMEOUT: Final[int] = 30  # seconds
HARDCOVER_RATE_LIMIT_DELAY: Final[float] = 1.0  # seconds between requests

# ─── Prowlarr ──────────────────────────────────────────────────────────────────
PROWLARR_RETRY_ATTEMPTS: Final[int] = 3
PROWLARR_TIMEOUT: Final[int] = 30  # seconds

# ─── qBittorrent ───────────────────────────────────────────────────────────────
QBIT_RETRY_ATTEMPTS: Final[int] = 3
QBIT_TIMEOUT: Final[int] = 30  # seconds

# ─── Kindle / SSH ──────────────────────────────────────────────────────────────
KINDLE_RETRY_ATTEMPTS: Final[int] = 3
KINDLE_SSH_TIMEOUT: Final[int] = 10  # seconds — connection timeout
KINDLE_TRANSFER_TIMEOUT: Final[int] = 300  # seconds — 5 min for large EPUBs
KINDLE_DELIVERY_TIMEOUT_DAYS: Final[int] = 14  # days before marking SKIPPED

# ─── Download / Stall ──────────────────────────────────────────────────────────
DOWNLOAD_STALL_THRESHOLD_MIN: Final[int] = 30  # minutes without progress
DOWNLOAD_TOTAL_TIMEOUT_HOURS: Final[int] = 24  # hard ceiling for any download

# ─── Pipeline / Retry ──────────────────────────────────────────────────────────
PIPELINE_AUTO_RETRY_ATTEMPTS: Final[int] = 3  # max auto-retries before PERMANENT_FAILED
RETRY_BASE_DELAY: Final[float] = 2.0  # seconds — first backoff interval
RETRY_MAX_DELAY: Final[float] = 60.0  # seconds — backoff ceiling

# ─── Reconciliation ────────────────────────────────────────────────────────────
RECONCILE_INTERVAL_MIN: Final[int] = 15  # minutes between reconciliation runs
PIPELINE_LOCK_STALE_THRESHOLD_HOURS: Final[int] = 1  # hours before stale lock is cleared

# ─── EPUB / Content Verification ───────────────────────────────────────────────
EPUB_TITLE_SIMILARITY_THRESHOLD: Final[float] = 0.75  # below this → low_confidence
EPUB_AUTHOR_MATCH_REQUIRED: Final[bool] = False  # if True, author match alone triggers accept

# ─── Import / Filesystem ───────────────────────────────────────────────────────
MAX_FILENAME_LENGTH: Final[int] = 200  # characters — truncate longer filenames
TMP_FILE_MAX_AGE_HOURS: Final[int] = 1  # hours — delete orphan .tmp files older than this
MAX_COLLISION_ATTEMPTS: Final[int] = 99  # max versioned suffix: (1), (2), ..., (99)

# ─── Search / Filtering ────────────────────────────────────────────────────────
SEARCH_MIN_SIZE_MB: Final[int] = 1  # MB — reject results smaller than this
SEARCH_MAX_SIZE_MB: Final[int] = 500  # MB — reject results larger than this
