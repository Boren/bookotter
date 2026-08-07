"""
Pipeline error taxonomy — failure reasons for all pipeline stages.
All raises in the pipeline must use FailureReason enum values.
"""

from enum import StrEnum


class FailureReason(StrEnum):
    # Hardcover
    HARDCOVER_UNREACHABLE = "hardcover_unreachable"
    HARDCOVER_AUTH_FAILED = "hardcover_auth_failed"
    HARDCOVER_RATE_LIMITED = "hardcover_rate_limited"
    # Search
    SEARCH_NO_RESULTS = "search_no_results"
    SEARCH_NO_APPROVED = "search_no_approved"
    SEARCH_NO_CANDIDATE_MATCHES_TITLE = "search_no_candidate_matches_title"
    PROWLARR_UNREACHABLE = "prowlarr_unreachable"
    PROWLARR_AUTH_FAILED = "prowlarr_auth_failed"
    # Download
    QBIT_UNREACHABLE = "qbit_unreachable"
    QBIT_AUTH_FAILED = "qbit_auth_failed"
    QBIT_REJECTED_TORRENT = "qbit_rejected_torrent"
    DOWNLOAD_DUPLICATE = "download_duplicate"
    DOWNLOAD_STALLED = "download_stalled"
    DOWNLOAD_TIMEOUT = "download_timeout"
    DOWNLOAD_TORRENT_ERROR = "download_torrent_error"
    DOWNLOAD_NO_EPUB = "download_no_epub"
    # Import
    IMPORT_INVALID_EPUB = "import_invalid_epub"
    IMPORT_DRM_PROTECTED = "import_drm_protected"
    IMPORT_DISK_FULL = "import_disk_full"
    IMPORT_FILE_COLLISION = "import_file_collision"
    IMPORT_COPY_FAILED = "import_copy_failed"
    IMPORT_METADATA_WRITE_FAILED = "import_metadata_write_failed"
    CONTENT_MISMATCH_LOW_CONFIDENCE = "content_mismatch_low_confidence"
    # E-reader
    EREADER_UNREACHABLE = "ereader_unreachable"
    EREADER_AUTH_FAILED = "ereader_auth_failed"
    EREADER_DISK_FULL = "ereader_disk_full"
    EREADER_TRANSFER_FAILED = "ereader_transfer_failed"
    # Pipeline
    PIPELINE_LOCK_HELD = "pipeline_lock_held"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    UNKNOWN = "unknown"


class PipelineError(Exception):
    """Pipeline-level exception with structured failure reason."""

    def __init__(self, message: str, reason: FailureReason) -> None:
        super().__init__(message)
        self.reason = reason
