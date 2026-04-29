"""Smoke tests for test fixture infrastructure."""

import asyncio

import pytest

from tests.fixtures.race_helpers import run_concurrently


class TestMockClock:
    def test_mock_clock_advances(self, mock_clock):
        t0 = mock_clock.now()
        mock_clock.advance(seconds=60)
        t1 = mock_clock.now()
        assert (t1 - t0).total_seconds() == pytest.approx(60.0, abs=1.0)

    def test_mock_clock_now_is_frozen(self, mock_clock):
        t0 = mock_clock.now()
        t1 = mock_clock.now()
        assert t0 == t1


class TestMockQBit:
    def test_mock_qbit_state_transitions(self, mock_qbit):
        from backend.clients.qbittorrent_client import TorrentState

        h = mock_qbit.add_torrent("magnet:?xt=urn:btih:abc")
        assert not mock_qbit.is_complete(h)

        mock_qbit.set_state(h, TorrentState.UPLOADING)
        assert mock_qbit.is_complete(h)

    def test_mock_qbit_add_returns_unique_hashes(self, mock_qbit):
        h1 = mock_qbit.add_torrent("magnet:?xt=urn:btih:aaa")
        h2 = mock_qbit.add_torrent("magnet:?xt=urn:btih:bbb")
        assert h1 != h2

    def test_mock_qbit_get_torrents(self, mock_qbit):
        mock_qbit.add_torrent("magnet:?xt=urn:btih:ccc")
        torrents = mock_qbit.get_torrents()
        assert len(torrents) == 1
        assert "hash" in torrents[0]


class TestRunConcurrently:
    def test_run_concurrently_collects_all(self):
        results_and_errors = asyncio.run(
            run_concurrently(
                [
                    lambda: 1,
                    lambda: 2,
                    lambda: (_ for _ in ()).throw(ValueError("oops")),
                ]
            )
        )
        values = [r for r, e in results_and_errors if e is None]
        errors = [e for r, e in results_and_errors if e is not None]
        assert len(values) == 2
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

    def test_run_concurrently_n_copies(self):
        call_count = []

        def counter():
            call_count.append(1)
            return len(call_count)

        asyncio.run(run_concurrently([counter], n=5))
        assert len(call_count) == 5
