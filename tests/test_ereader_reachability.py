"""Tests for EreaderClient.is_reachable TCP probe."""

import socket
from unittest.mock import MagicMock, patch

from backend.clients.ereader_client import EreaderClient
from backend.constants import EREADER_PROBE_TIMEOUT


def _make_client() -> EreaderClient:
    return EreaderClient(hostname="test-ereader", port=22)


class TestIsReachable:
    def test_reachable_when_tcp_connect_succeeds(self):
        client = _make_client()
        with patch("backend.clients.ereader_client.socket.create_connection") as create:
            create.return_value.__enter__ = MagicMock()
            create.return_value.__exit__ = MagicMock(return_value=False)
            assert client.is_reachable() is True
        create.assert_called_once_with(("test-ereader", 22), timeout=EREADER_PROBE_TIMEOUT)

    def test_unreachable_on_connection_refused(self):
        client = _make_client()
        with patch(
            "backend.clients.ereader_client.socket.create_connection",
            side_effect=ConnectionRefusedError(),
        ):
            assert client.is_reachable() is False

    def test_unreachable_on_timeout(self):
        client = _make_client()
        with patch(
            "backend.clients.ereader_client.socket.create_connection",
            side_effect=TimeoutError("timed out"),
        ):
            assert client.is_reachable() is False

    def test_unreachable_on_dns_failure(self):
        client = _make_client()
        with patch(
            "backend.clients.ereader_client.socket.create_connection",
            side_effect=socket.gaierror("name resolution failed"),
        ):
            assert client.is_reachable() is False

    def test_custom_timeout_forwarded(self):
        client = _make_client()
        with patch("backend.clients.ereader_client.socket.create_connection") as create:
            client.is_reachable(timeout=1.5)
        create.assert_called_once_with(("test-ereader", 22), timeout=1.5)
