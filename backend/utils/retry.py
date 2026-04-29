"""
Retry utility with exponential backoff.
Sync-only — the existing codebase is synchronous.
"""

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from backend.errors import FailureReason, PipelineError

logger = logging.getLogger(__name__)


def retry_with_backoff(
    attempts: int,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    failure_reason: FailureReason = FailureReason.UNKNOWN,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Callable:
    """
    Decorator factory: retries the decorated function up to `attempts` times
    with exponential backoff. Only retries the listed exception types.

    On final failure raises PipelineError(original_message, failure_reason)
    with the original exception as __cause__.

    sleep_fn is injectable for testing (pass lambda _: None to skip sleeps).
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < attempts:
                        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs due to %s: %s",
                            attempt,
                            attempts,
                            func.__name__,
                            delay,
                            type(exc).__name__,
                            exc,
                        )
                        sleep_fn(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            attempts,
                            func.__name__,
                            exc,
                        )
            raise PipelineError(str(last_exc), failure_reason) from last_exc

        return wrapper

    return decorator
