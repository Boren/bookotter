"""Shared throttled progress callback for Kindle file transfers."""

import time
from collections.abc import Callable

PROGRESS_EMIT_INTERVAL_SECONDS = 0.25


def make_progress_callback(
    emit: Callable[[str, dict], None],
    event_name: str,
    payload_base: dict | None = None,
) -> Callable[[int, int], None]:
    """Build a (bytes_so_far, bytes_total) callback that emits throttled WS events.

    Emits at most every 250ms, but always emits the final chunk. Each event
    carries payload_base merged with bytes/percentage/speed/ETA fields.
    """
    base = dict(payload_base or {})
    transfer_start = time.time()
    last_emit_time = [0.0]

    def progress_callback(bytes_so_far: int, bytes_total: int) -> None:
        now = time.time()
        if now - last_emit_time[0] < PROGRESS_EMIT_INTERVAL_SECONDS and bytes_so_far < bytes_total:
            return
        last_emit_time[0] = now

        elapsed = now - transfer_start
        speed = bytes_so_far / elapsed if elapsed > 0 else 0
        remaining = (bytes_total - bytes_so_far) / speed if speed > 0 else 0
        percentage = (bytes_so_far / bytes_total * 100) if bytes_total > 0 else 0

        emit(
            event_name,
            {
                **base,
                "bytes_transferred": bytes_so_far,
                "bytes_total": bytes_total,
                "percentage": round(percentage, 1),
                "speed_bytes_per_sec": round(speed),
                "eta_seconds": round(remaining),
            },
        )

    return progress_callback
