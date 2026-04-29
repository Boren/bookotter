"""Tests for Kindle client retry behavior and SSH connection pool."""

import socket
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from backend.clients.kindle_client import KindleClient
from backend.constants import KINDLE_RETRY_ATTEMPTS
from backend.errors import FailureReason, PipelineError
from backend.utils.retry import retry_with_backoff

KINDLE_CONFIG = {
    "hostname": "test-kindle",
    "port": 22,
    "username": "root",
    "password": "",
    "ssh_key_path": "",
}


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    # The retry decorator captures `time.sleep` as the default sleep_fn at
    # module load, so monkey-patching time.sleep cannot speed up the already
    # decorated method. Re-decorate _connect_ssh.__wrapped__ with a no-op
    # sleep so retry tests run instantly while preserving retry semantics.
    unwrapped = KindleClient._connect_ssh.__wrapped__  # type: ignore[attr-defined]
    fast = retry_with_backoff(
        attempts=KINDLE_RETRY_ATTEMPTS,
        exceptions=(paramiko.SSHException, OSError, socket.error),
        failure_reason=FailureReason.KINDLE_UNREACHABLE,
        sleep_fn=lambda _: None,
    )(unwrapped)
    monkeypatch.setattr(KindleClient, "_connect_ssh", fast)


class TestKindleRetry:
    def test_connection_retry_on_ssh_exception(self):
        """SSHException is retried; eventual success returns the client."""
        connect_calls = [0]

        def side_effect(*args, **kwargs):
            connect_calls[0] += 1
            if connect_calls[0] < 3:
                raise paramiko.SSHException("connection failed")

        active_transport = MagicMock()
        active_transport.is_active.return_value = True

        with (
            patch.object(paramiko.SSHClient, "connect", side_effect=side_effect),
            patch.object(paramiko.SSHClient, "get_transport", return_value=active_transport),
        ):
            client = KindleClient(hostname="test-kindle")
            ssh = client._get_or_create_ssh(KINDLE_CONFIG)

            assert isinstance(ssh, paramiko.SSHClient)
            assert connect_calls[0] == 3

    def test_auth_failure_no_retry(self):
        """AuthenticationException raises PipelineError immediately, no retry."""
        connect_calls = [0]

        def side_effect(*args, **kwargs):
            connect_calls[0] += 1
            raise paramiko.AuthenticationException("bad key")

        with patch.object(paramiko.SSHClient, "connect", side_effect=side_effect):
            client = KindleClient(hostname="test-kindle")
            with pytest.raises(PipelineError) as exc_info:
                client._get_or_create_ssh(KINDLE_CONFIG)

            assert exc_info.value.reason == FailureReason.KINDLE_AUTH_FAILED
            assert connect_calls[0] == 1

    def test_pool_reuses_connection(self):
        """Three sequential _get_or_create_ssh calls share one SSH connect."""
        connect_calls = [0]

        def side_effect(*args, **kwargs):
            connect_calls[0] += 1

        active_transport = MagicMock()
        active_transport.is_active.return_value = True

        with (
            patch.object(paramiko.SSHClient, "connect", side_effect=side_effect),
            patch.object(paramiko.SSHClient, "get_transport", return_value=active_transport),
        ):
            client = KindleClient(hostname="test-kindle")
            for _ in range(3):
                client._get_or_create_ssh(KINDLE_CONFIG)

            assert connect_calls[0] == 1

    def test_pool_reconnects_broken_transport(self):
        """Broken transport (is_active=False) triggers close + reconnect."""
        connect_calls = [0]

        def side_effect(*args, **kwargs):
            connect_calls[0] += 1

        broken_transport = MagicMock()
        broken_transport.is_active.return_value = False

        with (
            patch.object(paramiko.SSHClient, "connect", side_effect=side_effect),
            patch.object(paramiko.SSHClient, "get_transport", return_value=broken_transport),
        ):
            client = KindleClient(hostname="test-kindle")

            client._get_or_create_ssh(KINDLE_CONFIG)
            assert connect_calls[0] == 1

            client._get_or_create_ssh(KINDLE_CONFIG)
            assert connect_calls[0] == 2
