"""Mock clock fixture using freezegun for deterministic time control."""

from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time


class MockClock:
    """Controllable mock clock wrapping freezegun."""

    def __init__(self, frozen_datetime):
        self._frozen = frozen_datetime
        self._current = datetime(2024, 1, 1, 0, 0, 0)

    def advance(self, seconds: float) -> None:
        """Advance frozen time by N seconds."""
        new_time = self._current + timedelta(seconds=seconds)
        self._current = new_time
        self._frozen.move_to(new_time)

    def now(self) -> datetime:
        """Return current frozen time."""
        return datetime.utcnow()


@pytest.fixture
def mock_clock():
    """Pytest fixture providing a controllable mock clock."""
    with freeze_time("2024-01-01 00:00:00") as frozen_datetime:
        yield MockClock(frozen_datetime)
