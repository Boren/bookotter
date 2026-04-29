import pytest

from backend.errors import FailureReason, PipelineError
from backend.utils.retry import retry_with_backoff


class TestRetryWithBackoff:
    def test_succeeds_first_try_no_retries(self):
        calls = []

        @retry_with_backoff(attempts=3, sleep_fn=lambda _: None)
        def succeed():
            calls.append(1)
            return "ok"

        result = succeed()
        assert result == "ok"
        assert len(calls) == 1

    def test_succeeds_on_third_try(self):
        attempts_made = []

        @retry_with_backoff(attempts=3, exceptions=(ValueError,), sleep_fn=lambda _: None)
        def fail_twice():
            attempts_made.append(1)
            if len(attempts_made) < 3:
                raise ValueError("not yet")
            return "done"

        result = fail_twice()
        assert result == "done"
        assert len(attempts_made) == 3

    def test_all_fail_raises_pipeline_error(self):
        @retry_with_backoff(
            attempts=3,
            exceptions=(ValueError,),
            failure_reason=FailureReason.HARDCOVER_UNREACHABLE,
            sleep_fn=lambda _: None,
        )
        def always_fails():
            raise ValueError("boom")

        with pytest.raises(PipelineError) as exc_info:
            always_fails()

        assert exc_info.value.reason == FailureReason.HARDCOVER_UNREACHABLE

    def test_backoff_sequence_is_2_4_8_16_capped(self):
        sleeps = []

        @retry_with_backoff(
            attempts=7,
            base_delay=2.0,
            max_delay=60.0,
            exceptions=(ValueError,),
            sleep_fn=lambda d: sleeps.append(d),
        )
        def always_fails():
            raise ValueError("boom")

        with pytest.raises(PipelineError):
            always_fails()

        assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0]

    def test_unlisted_exception_propagates_immediately(self):
        sleeps = []

        @retry_with_backoff(
            attempts=3,
            exceptions=(ValueError,),
            sleep_fn=lambda d: sleeps.append(d),
        )
        def raise_type_error():
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            raise_type_error()

        assert sleeps == []

    def test_original_exception_preserved_as_cause(self):
        original = ValueError("original error")

        @retry_with_backoff(
            attempts=2,
            exceptions=(ValueError,),
            failure_reason=FailureReason.UNKNOWN,
            sleep_fn=lambda _: None,
        )
        def always_fails():
            raise original

        with pytest.raises(PipelineError) as exc_info:
            always_fails()

        assert exc_info.value.__cause__ is original
