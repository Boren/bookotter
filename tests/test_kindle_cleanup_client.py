"""Tests for KindleClient orphan detection and batched cleanup deletion."""

from unittest.mock import MagicMock, patch

from backend.clients.kindle_client import KindleClient


def _make_client() -> KindleClient:
    return KindleClient(hostname="test-kindle", destination_path="/mnt/us/books/")


def _mock_ssh_with_find_output(find_output: str) -> MagicMock:
    ssh = MagicMock()
    stdout = MagicMock()
    stdout.read.return_value = find_output.encode()
    stdout.channel.recv_exit_status.return_value = 0
    ssh.exec_command.return_value = (MagicMock(), stdout, MagicMock())
    return ssh


class TestFindOrphanedBooks:
    def test_basename_matching_across_subfolders(self):
        client = _make_client()
        ssh = _mock_ssh_with_find_output(
            "/mnt/us/books/keep.epub\n/mnt/us/books/Author/Series/nested-keep.epub\n/mnt/us/books/orphan.epub"
        )
        with patch.object(client, "_create_ssh_client", return_value=ssh):
            orphans = client.find_orphaned_books(
                ["/mnt/us/books/keep.epub", "/mnt/us/books/Other Author/nested-keep.epub"]
            )

        # Expected paths match by basename, so the nested file survives even
        # though its expected path uses a different folder layout
        assert orphans == ["/mnt/us/books/orphan.epub"]

    def test_protected_paths_excluded(self):
        client = _make_client()
        ssh = _mock_ssh_with_find_output("/mnt/us/books/koreader/dict.epub\n/mnt/us/books/orphan.epub")
        with patch.object(client, "_create_ssh_client", return_value=ssh):
            orphans = client.find_orphaned_books([], protected_paths=["/mnt/us/books/koreader/"])

        assert orphans == ["/mnt/us/books/orphan.epub"]

    def test_listing_failure_yields_no_orphans(self):
        client = _make_client()
        with patch.object(client, "_create_ssh_client", side_effect=RuntimeError("offline")):
            orphans = client.find_orphaned_books(["/mnt/us/books/keep.epub"])

        assert orphans == []


class TestCleanupOrphanedBooks:
    def _delete_ssh(self, exit_status: int = 0) -> MagicMock:
        ssh = MagicMock()
        stdout = MagicMock()
        stdout.read.return_value = b""
        stdout.channel.recv_exit_status.return_value = exit_status
        ssh.exec_command.return_value = (MagicMock(), stdout, MagicMock())
        return ssh

    def test_single_connection_for_all_deletions(self):
        client = _make_client()
        ssh = self._delete_ssh()
        orphans = [f"/mnt/us/books/orphan-{i}.epub" for i in range(5)]
        with (
            patch.object(client, "find_orphaned_books", return_value=orphans),
            patch.object(client, "_create_ssh_client", return_value=ssh) as create,
        ):
            result = client.cleanup_orphaned_books([], delete_sdr=True)

        assert result == {"total_orphans": 5, "deleted": 5, "failed": 0}
        create.assert_called_once()
        ssh.close.assert_called_once()
        # rm for the file + rm -rf for the .sdr folder, per orphan
        assert ssh.exec_command.call_count == 10

    def test_no_connection_when_no_orphans(self):
        client = _make_client()
        with (
            patch.object(client, "find_orphaned_books", return_value=[]),
            patch.object(client, "_create_ssh_client") as create,
        ):
            result = client.cleanup_orphaned_books([])

        assert result == {"total_orphans": 0, "deleted": 0, "failed": 0}
        create.assert_not_called()

    def test_failed_rm_counts_as_failed(self):
        client = _make_client()
        ssh = self._delete_ssh(exit_status=1)
        with (
            patch.object(client, "find_orphaned_books", return_value=["/mnt/us/books/orphan.epub"]),
            patch.object(client, "_create_ssh_client", return_value=ssh),
        ):
            result = client.cleanup_orphaned_books([])

        assert result == {"total_orphans": 1, "deleted": 0, "failed": 1}
        ssh.close.assert_called_once()

    def test_reconnects_once_when_connection_drops(self):
        client = _make_client()
        dead_ssh = MagicMock()
        dead_ssh.exec_command.side_effect = OSError("connection lost")
        live_ssh = self._delete_ssh()
        with (
            patch.object(client, "find_orphaned_books", return_value=["/mnt/us/books/orphan.epub"]),
            patch.object(client, "_create_ssh_client", side_effect=[dead_ssh, live_ssh]) as create,
        ):
            result = client.cleanup_orphaned_books([])

        assert result == {"total_orphans": 1, "deleted": 1, "failed": 0}
        assert create.call_count == 2
        dead_ssh.close.assert_called_once()
        live_ssh.close.assert_called_once()

    def test_sdr_not_deleted_when_disabled(self):
        client = _make_client()
        ssh = self._delete_ssh()
        with (
            patch.object(client, "find_orphaned_books", return_value=["/mnt/us/books/orphan.epub"]),
            patch.object(client, "_create_ssh_client", return_value=ssh),
        ):
            result = client.cleanup_orphaned_books([], delete_sdr=False)

        assert result["deleted"] == 1
        commands = [c[0][0] for c in ssh.exec_command.call_args_list]
        assert not any(".sdr" in cmd for cmd in commands)
