"""In-memory qBittorrent state machine for testing."""

import pytest

from backend.clients.qbittorrent_client import DOWNLOAD_COMPLETE_STATES, TorrentState


class MockQBitTorrent:
    """In-memory representation of a torrent."""

    def __init__(self, magnet: str, torrent_hash: str):
        self.magnet = magnet
        self.hash = torrent_hash
        self.state = TorrentState.DOWNLOADING
        self.progress = 0.0
        self.name = torrent_hash
        self.size = 1024 * 1024  # 1MB
        self.content_path = ""


class MockQBitClient:
    """In-memory qBittorrent state machine matching QBittorrentClient protocol."""

    def __init__(self):
        self._torrents: dict[str, MockQBitTorrent] = {}
        self._counter = 0

    def add_torrent(self, magnet_url: str, save_path: str = "") -> str:
        """Add torrent and return its hash."""
        self._counter += 1
        torrent_hash = f"mock_hash_{self._counter:040x}"
        self._torrents[torrent_hash] = MockQBitTorrent(magnet_url, torrent_hash)
        return torrent_hash

    def set_state(self, torrent_hash: str, state: TorrentState) -> None:
        """Set torrent state (for test control)."""
        if torrent_hash in self._torrents:
            self._torrents[torrent_hash].state = state

    def set_progress(self, torrent_hash: str, fraction: float) -> None:
        """Set torrent progress 0.0-1.0."""
        if torrent_hash in self._torrents:
            self._torrents[torrent_hash].progress = fraction

    def get_torrents(self) -> list[dict]:
        """Return all torrents as dicts (matching qBit API)."""
        result = []
        for t in self._torrents.values():
            result.append(
                {
                    "hash": t.hash,
                    "state": t.state.value,
                    "progress": t.progress,
                    "name": t.name,
                    "size": t.size,
                    "content_path": t.content_path,
                    "save_path": "",
                }
            )
        return result

    def get_torrent_info(self, torrent_hash: str) -> dict | None:
        """Return single torrent info."""
        t = self._torrents.get(torrent_hash)
        if t is None:
            return None
        return {
            "hash": t.hash,
            "state": t.state.value,
            "progress": t.progress,
            "name": t.name,
            "size": t.size,
            "content_path": t.content_path,
            "save_path": "",
        }

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> None:
        """Remove torrent."""
        self._torrents.pop(torrent_hash, None)

    def is_complete(self, torrent_hash: str) -> bool:
        """Return True if torrent is in complete states."""
        t = self._torrents.get(torrent_hash)
        if t is None:
            return False
        return TorrentState(t.state) in DOWNLOAD_COMPLETE_STATES or t.progress >= 1.0


@pytest.fixture
def mock_qbit():
    """Pytest fixture providing an in-memory qBittorrent mock."""
    return MockQBitClient()
