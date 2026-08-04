"""Tests for Kindle atomic SFTP transfer + free-space check + .tmp cleanup."""

from unittest.mock import MagicMock, patch

import pytest

from backend.clients.kindle_client import KindleClient
from backend.errors import FailureReason, PipelineError


def _make_exec_response(payload: bytes = b"", exit_status: int = 0):
    """Build a (stdin, stdout, stderr) tuple matching paramiko.SSHClient.exec_command()."""
    stdin = MagicMock()
    stdout = MagicMock()
    stderr = MagicMock()
    stdout.read.return_value = payload
    stdout.channel.recv_exit_status.return_value = exit_status
    stderr.read.return_value = b""
    return stdin, stdout, stderr


def _make_mock_ssh(exec_returns: list[tuple[bytes, int]]):
    """Build a mock SSH client whose exec_command returns the given payloads in order."""
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp
    mock_ssh.exec_command.side_effect = [_make_exec_response(p, s) for p, s in exec_returns]
    return mock_ssh, mock_sftp


def _mv_calls(mock_ssh: MagicMock) -> list:
    return [c for c in mock_ssh.exec_command.call_args_list if c[0][0].startswith("mv ")]


class TestAtomicTransfer:
    def test_normal_transfer_no_tmp_on_kindle(self, tmp_path):
        """Normal transfer uploads to .tmp then renames — final file at dest, no .tmp lingering."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        # Sequence of exec_command calls:
        #   1. _file_exists_sftp test -f → "" (does not exist)
        #   2. df → 100 MB available (in 1K-blocks)
        #   3. mv → exit 0
        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"102400", 0), (b"", 0)])
        mock_stat = MagicMock()
        mock_stat.st_size = 1024
        mock_sftp.stat.return_value = mock_stat

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result == {"success": True, "status": "transferred", "file_size": 1024}

        mock_sftp.put.assert_called_once()
        put_args = mock_sftp.put.call_args
        assert put_args[0][0] == str(src)
        assert put_args[0][1] == "/mnt/us/books/book.epub.tmp"

        mv = _mv_calls(mock_ssh)
        assert len(mv) == 1
        assert "/mnt/us/books/book.epub.tmp" in mv[0][0][0]
        assert "/mnt/us/books/book.epub" in mv[0][0][0]
        mock_sftp.remove.assert_not_called()

    def test_disk_full_raises_no_transfer(self, tmp_path):
        """Insufficient space → PipelineError(KINDLE_DISK_FULL); sftp.put NOT called."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 200 * 1024)

        # Sequence: test -f → "", df → 100 KB available (need 220 KB with 1.1x margin)
        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"100", 0)])

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with (
            patch.object(client, "_create_ssh_client", return_value=mock_ssh),
            pytest.raises(PipelineError) as exc_info,
        ):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert exc_info.value.reason == FailureReason.KINDLE_DISK_FULL
        mock_sftp.put.assert_not_called()
        assert _mv_calls(mock_ssh) == []

    def test_transfer_interrupted_no_partial(self, tmp_path):
        """sftp.put raises mid-flight → .tmp cleanup attempted, mv NOT called, no partial at dest."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"102400", 0)])
        mock_sftp.put.side_effect = OSError("connection lost")

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result["success"] is False
        assert result["status"] == "failed"

        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []

    def test_size_mismatch_raises_transfer_failed(self, tmp_path):
        """sftp.put succeeds but remote size != local size → KINDLE_TRANSFER_FAILED + .tmp removed + no mv."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"102400", 0)])
        # sftp.stat reports 999 bytes — does not match local 1024
        mock_stat = MagicMock()
        mock_stat.st_size = 999
        mock_sftp.stat.return_value = mock_stat

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with (
            patch.object(client, "_create_ssh_client", return_value=mock_ssh),
            pytest.raises(PipelineError) as exc_info,
        ):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert exc_info.value.reason == FailureReason.KINDLE_TRANSFER_FAILED
        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []


class TestTransferTimeout:
    def test_channel_timeout_set_before_put(self, tmp_path):
        """The SFTP channel gets KINDLE_TRANSFER_TIMEOUT applied before the upload starts."""
        from backend.constants import KINDLE_TRANSFER_TIMEOUT

        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"102400", 0), (b"", 0)])
        mock_stat = MagicMock()
        mock_stat.st_size = 1024
        mock_sftp.stat.return_value = mock_stat

        calls: list[str] = []
        mock_sftp.get_channel.return_value.settimeout.side_effect = lambda t: calls.append(("settimeout", t))
        mock_sftp.put.side_effect = lambda *a, **k: calls.append(("put",))

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert calls[0] == ("settimeout", KINDLE_TRANSFER_TIMEOUT)
        assert ("put",) in calls

    def test_put_socket_timeout_cleans_tmp(self, tmp_path):
        """A stalled upload (socket.timeout) fails softly and attempts .tmp cleanup."""

        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"", 0), (b"102400", 0)])
        mock_sftp.put.side_effect = TimeoutError("timed out")

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result["success"] is False
        assert result["status"] == "failed"
        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []


class TestCleanupTmpFiles:
    def test_old_tmp_cleaned_by_cleanup_pass(self):
        """cleanup_kindle_tmp_files runs `find -delete -print` and returns the deletion count."""
        find_output = b"/mnt/us/books/a.epub.tmp\n/mnt/us/books/b.epub.tmp\n/mnt/us/books/c.epub.tmp"
        mock_ssh, _ = _make_mock_ssh([(find_output, 0)])

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            count = client.cleanup_kindle_tmp_files(max_age_hours=1)

        assert count == 3
        find_cmd = mock_ssh.exec_command.call_args_list[0][0][0]
        assert "find" in find_cmd
        assert "-name '*.tmp'" in find_cmd
        assert "-mmin +60" in find_cmd  # 1h * 60min
        assert "-delete" in find_cmd
        assert "-print" in find_cmd

    def test_cleanup_no_tmp_files_returns_zero(self):
        """No matching .tmp files → empty find output → returns 0."""
        mock_ssh, _ = _make_mock_ssh([(b"", 0)])

        client = KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            count = client.cleanup_kindle_tmp_files()

        assert count == 0
