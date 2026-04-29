"""Sanity tests for backend.constants module."""

import backend.constants as C


class TestConstantRanges:
    def test_retry_attempts_in_range(self):
        for attr in [
            "HARDCOVER_RETRY_ATTEMPTS",
            "PROWLARR_RETRY_ATTEMPTS",
            "QBIT_RETRY_ATTEMPTS",
            "KINDLE_RETRY_ATTEMPTS",
            "PIPELINE_AUTO_RETRY_ATTEMPTS",
        ]:
            val = getattr(C, attr)
            assert 1 <= val <= 10, f"{attr}={val} out of range [1, 10]"

    def test_timeouts_in_range(self):
        for attr in [
            "HARDCOVER_TIMEOUT",
            "PROWLARR_TIMEOUT",
            "QBIT_TIMEOUT",
            "KINDLE_SSH_TIMEOUT",
        ]:
            val = getattr(C, attr)
            assert 1 <= val <= 3600, f"{attr}={val} out of range [1, 3600]"

    def test_similarity_thresholds_in_range(self):
        assert 0.0 <= C.EPUB_TITLE_SIMILARITY_THRESHOLD <= 1.0

    def test_all_positive(self):
        for name in dir(C):
            if name.startswith("_"):
                continue
            val = getattr(C, name)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                assert val > 0, f"{name}={val} is not positive"

    def test_key_constants_exist(self):
        assert hasattr(C, "HARDCOVER_RETRY_ATTEMPTS")
        assert hasattr(C, "DOWNLOAD_STALL_THRESHOLD_MIN")
        assert hasattr(C, "EPUB_TITLE_SIMILARITY_THRESHOLD")
        assert hasattr(C, "KINDLE_DELIVERY_TIMEOUT_DAYS")
        assert hasattr(C, "PIPELINE_AUTO_RETRY_ATTEMPTS")
        assert hasattr(C, "MAX_FILENAME_LENGTH")
        assert hasattr(C, "RECONCILE_INTERVAL_MIN")
