"""Tests for E-reader atomic SFTP transfer + free-space check + .tmp cleanup."""

from unittest.mock import MagicMock, patch

import pytest

from backend.clients.ereader_client import EreaderClient
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


def _stat_side_effect(remote_size: int | None, tmp_size: int):
    """sftp.stat side_effect: final path has remote_size (None → missing), .tmp has tmp_size."""

    def _stat(path):
        st = MagicMock()
        if path.endswith(".tmp"):
            st.st_size = tmp_size
            return st
        if remote_size is None:
            raise FileNotFoundError(path)
        st.st_size = remote_size
        return st

    return _stat


def _stat_missing_remote(tmp_size: int):
    return _stat_side_effect(remote_size=None, tmp_size=tmp_size)


class TestAtomicTransfer:
    def test_normal_transfer_no_tmp_on_ereader(self, tmp_path):
        """Normal transfer uploads to .tmp then renames — final file at dest, no .tmp lingering."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        # Sequence of exec_command calls:
        #   1. df → 100 MB available (in 1K-blocks)
        #   2. mv → exit 0
        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0), (b"", 0)])
        mock_sftp.stat.side_effect = _stat_missing_remote(tmp_size=1024)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

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
        """Insufficient space → PipelineError(EREADER_DISK_FULL); sftp.put NOT called."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 200 * 1024)

        # Sequence: df → 100 KB available (need 220 KB with 1.1x margin)
        mock_ssh, mock_sftp = _make_mock_ssh([(b"100", 0)])
        mock_sftp.stat.side_effect = _stat_missing_remote(tmp_size=200 * 1024)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with (
            patch.object(client, "_create_ssh_client", return_value=mock_ssh),
            pytest.raises(PipelineError) as exc_info,
        ):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert exc_info.value.reason == FailureReason.EREADER_DISK_FULL
        mock_sftp.put.assert_not_called()
        assert _mv_calls(mock_ssh) == []

    def test_transfer_interrupted_no_partial(self, tmp_path):
        """sftp.put raises mid-flight → .tmp cleanup attempted, mv NOT called, no partial at dest."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0)])
        mock_sftp.stat.side_effect = _stat_missing_remote(tmp_size=1024)
        mock_sftp.put.side_effect = OSError("connection lost")

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result["success"] is False
        assert result["status"] == "failed"

        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []

    def test_size_mismatch_raises_transfer_failed(self, tmp_path):
        """sftp.put succeeds but remote size != local size → EREADER_TRANSFER_FAILED + .tmp removed + no mv."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0)])
        # .tmp lands at 999 bytes — does not match local 1024
        mock_sftp.stat.side_effect = _stat_side_effect(remote_size=None, tmp_size=999)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with (
            patch.object(client, "_create_ssh_client", return_value=mock_ssh),
            pytest.raises(PipelineError) as exc_info,
        ):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert exc_info.value.reason == FailureReason.EREADER_TRANSFER_FAILED
        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []


class TestStaleRemoteOverwrite:
    """skip_existing must compare remote size, not mere existence — a metadata
    rewrite changes the local file, and the stale E-reader copy must be replaced."""

    def test_same_size_remote_is_skipped(self, tmp_path):
        """Remote file with identical size → skipped, nothing uploaded."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0), (b"", 0)])
        mock_sftp.stat.side_effect = _stat_side_effect(remote_size=1024, tmp_size=1024)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result == {"success": True, "status": "skipped", "file_size": 0}
        mock_sftp.put.assert_not_called()
        assert _mv_calls(mock_ssh) == []

    def test_stale_remote_is_overwritten(self, tmp_path):
        """Remote file exists but size differs (stale metadata) → full transfer replaces it."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        # Sequence: df → 100 MB, mv → exit 0
        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0), (b"", 0)])
        mock_sftp.stat.side_effect = _stat_side_effect(remote_size=999, tmp_size=1024)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result == {"success": True, "status": "transferred", "file_size": 1024}
        mock_sftp.put.assert_called_once()
        assert len(_mv_calls(mock_ssh)) == 1

    def test_missing_remote_is_transferred(self, tmp_path):
        """No remote file at all → normal transfer."""
        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0), (b"", 0)])
        mock_sftp.stat.side_effect = _stat_side_effect(remote_size=None, tmp_size=1024)

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result == {"success": True, "status": "transferred", "file_size": 1024}
        mock_sftp.put.assert_called_once()


class TestTransferTimeout:
    def test_channel_timeout_set_before_put(self, tmp_path):
        """The SFTP channel gets EREADER_TRANSFER_TIMEOUT applied before the upload starts."""
        from backend.constants import EREADER_TRANSFER_TIMEOUT

        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0), (b"", 0)])
        mock_sftp.stat.side_effect = _stat_missing_remote(tmp_size=1024)

        calls: list[str] = []
        mock_sftp.get_channel.return_value.settimeout.side_effect = lambda t: calls.append(("settimeout", t))
        mock_sftp.put.side_effect = lambda *a, **k: calls.append(("put",))

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert calls[0] == ("settimeout", EREADER_TRANSFER_TIMEOUT)
        assert ("put",) in calls

    def test_put_socket_timeout_cleans_tmp(self, tmp_path):
        """A stalled upload (socket.timeout) fails softly and attempts .tmp cleanup."""

        src = tmp_path / "book.epub"
        src.write_bytes(b"X" * 1024)

        mock_ssh, mock_sftp = _make_mock_ssh([(b"102400", 0)])
        mock_sftp.stat.side_effect = _stat_missing_remote(tmp_size=1024)
        mock_sftp.put.side_effect = TimeoutError("timed out")

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            result = client.transfer_file(str(src), skip_existing=True, folder_organization="flat")

        assert result["success"] is False
        assert result["status"] == "failed"
        mock_sftp.remove.assert_called_with("/mnt/us/books/book.epub.tmp")
        assert _mv_calls(mock_ssh) == []


class TestCleanupTmpFiles:
    def test_old_tmp_cleaned_by_cleanup_pass(self):
        """cleanup_ereader_tmp_files runs `find -delete -print` and returns the deletion count."""
        find_output = b"/mnt/us/books/a.epub.tmp\n/mnt/us/books/b.epub.tmp\n/mnt/us/books/c.epub.tmp"
        mock_ssh, _ = _make_mock_ssh([(find_output, 0)])

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            count = client.cleanup_ereader_tmp_files(max_age_hours=1)

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

        client = EreaderClient(hostname="test-ereader", destination_path="/mnt/us/books/")

        with patch.object(client, "_create_ssh_client", return_value=mock_ssh):
            count = client.cleanup_ereader_tmp_files()

        assert count == 0
