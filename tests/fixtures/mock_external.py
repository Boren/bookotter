"""In-memory mocks for external service clients."""

import pytest


class MockHardcoverClient:
    """In-memory mock for HardcoverClient."""

    def __init__(self, books: list[dict] | None = None):
        self._books = books or []
        self.call_count = 0

    def get_want_to_read(self) -> list[dict]:
        self.call_count += 1
        return list(self._books)

    def set_books(self, books: list[dict]) -> None:
        self._books = list(books)


class MockProwlarrClient:
    """In-memory mock for ProwlarrClient."""

    def __init__(self, results: list[dict] | None = None):
        self._results = results or []
        self.search_count = 0

    def search(self, query: str, **kwargs) -> list[dict]:
        self.search_count += 1
        return list(self._results)

    def set_results(self, results: list[dict]) -> None:
        self._results = list(results)


class MockEreaderClient:
    """In-memory mock for EreaderClient."""

    def __init__(self, reachable: bool = True):
        self.reachable = reachable
        self.transfer_count = 0
        self.transferred_files: list[tuple] = []

    def is_reachable(self) -> bool:
        return self.reachable

    def transfer_file(self, local_path: str, remote_path: str) -> None:
        if not self.reachable:
            raise ConnectionError("E-reader unreachable")
        self.transfer_count += 1
        self.transferred_files.append((local_path, remote_path))


@pytest.fixture
def mock_hardcover():
    return MockHardcoverClient()


@pytest.fixture
def mock_prowlarr():
    return MockProwlarrClient()


@pytest.fixture
def mock_ereader():
    return MockEreaderClient()
