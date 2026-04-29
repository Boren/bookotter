"""Tests for backend.errors module."""

from backend.errors import FailureReason, PipelineError


class TestFailureReasonEnum:
    def test_all_values_unique_lowercase(self):
        values = [r.value for r in FailureReason]
        assert len(values) == len(set(values)), "Duplicate FailureReason values detected"
        for val in values:
            assert val == val.lower(), f"Value '{val}' is not lowercase"
            assert "_" in val or val.isalpha(), f"Value '{val}' should be snake_case"

    def test_hardcover_unreachable_value(self):
        assert FailureReason.HARDCOVER_UNREACHABLE.value == "hardcover_unreachable"

    def test_permanent_failed_reason_exists(self):
        assert FailureReason.RETRY_BUDGET_EXHAUSTED.value == "retry_budget_exhausted"

    def test_pipeline_lock_held_reason_exists(self):
        assert FailureReason.PIPELINE_LOCK_HELD.value == "pipeline_lock_held"


class TestPipelineError:
    def test_pipeline_error_carries_reason(self):
        err = PipelineError("test error", FailureReason.UNKNOWN)
        assert err.reason == FailureReason.UNKNOWN
        assert str(err) == "test error"

    def test_pipeline_error_is_exception(self):
        err = PipelineError("msg", FailureReason.HARDCOVER_UNREACHABLE)
        assert isinstance(err, Exception)
        assert err.reason == FailureReason.HARDCOVER_UNREACHABLE

    def test_pipeline_error_with_cause(self):
        try:
            original = ValueError("original")
            try:
                raise original
            except ValueError as e:
                raise PipelineError("wrapped", FailureReason.UNKNOWN) from e
        except PipelineError as wrapped:
            assert wrapped.__cause__ is original
