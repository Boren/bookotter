"""
Kindle SSH/SFTP Client
Handles SSH connections and file transfers to Kindle devices.
"""

import logging
import os
import shlex
import socket
import stat
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import paramiko

from backend.clients import ConnectionTestResult, classify_ssh_error
from backend.constants import (
    KINDLE_PROBE_TIMEOUT,
    KINDLE_RETRY_ATTEMPTS,
    KINDLE_SSH_TIMEOUT,
    KINDLE_TRANSFER_TIMEOUT,
    TMP_FILE_MAX_AGE_HOURS,
)
from backend.errors import FailureReason, PipelineError
from backend.utils.filesystem import DirectoryEntry
from backend.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)


class KindleNotFoundError(Exception):
    pass


class KindlePermissionError(Exception):
    pass


class KindleConnectionError(Exception):
    pass


class KindleTimeoutError(Exception):
    pass


class KindleClient:
    """Client for interacting with Kindle devices via SSH/SFTP."""

    def __init__(
        self,
        hostname: str,
        username: str = "root",
        port: int = 22,
        password: str | None = None,
        ssh_key_path: str | None = None,
        destination_path: str = "/mnt/us/books/",
    ):
        """
        Initialize the Kindle client.

        Args:
            hostname: Kindle's hostname or IP (e.g., Tailscale hostname)
            username: SSH username (usually 'root' for jailbroken Kindles)
            port: SSH port (default: 22)
            password: SSH password (if using password auth)
            ssh_key_path: Path to SSH private key (if using key auth)
            destination_path: Destination folder on Kindle for books
        """
        self.hostname = hostname
        self.username = username
        self.port = port
        self.password = password
        self.ssh_key_path = ssh_key_path
        self.destination_path = destination_path.rstrip("/") + "/"
        self._ssh_pool: dict[str, paramiko.SSHClient] = {}

    @classmethod
    def from_config(cls, config: dict) -> KindleClient:
        """Create a KindleClient from a configuration dictionary."""
        return cls(
            hostname=config.get("hostname", ""),
            username=config.get("username", "root"),
            port=config.get("port", 22),
            password=config.get("password"),
            ssh_key_path=config.get("ssh_key_path"),
            destination_path=config.get("destination_path", "/mnt/us/books/"),
        )

    def _create_ssh_client(self) -> paramiko.SSHClient:
        """
        Create and connect an SSH client to the Kindle.

        Returns:
            Connected SSH client

        Raises:
            Exception: If connection fails
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "timeout": KINDLE_SSH_TIMEOUT,
        }

        # Use either password or key authentication
        if self.password:
            connect_kwargs["password"] = self.password
        elif self.ssh_key_path:
            key_path = os.path.expanduser(self.ssh_key_path)
            connect_kwargs["key_filename"] = key_path

        ssh.connect(**connect_kwargs)
        return ssh

    @retry_with_backoff(
        attempts=KINDLE_RETRY_ATTEMPTS,
        exceptions=(paramiko.SSHException, OSError, socket.error),
        failure_reason=FailureReason.KINDLE_UNREACHABLE,
    )
    def _connect_ssh(self, kindle_config: dict) -> paramiko.SSHClient:
        """
        Open a fresh SSH connection to the Kindle described by kindle_config.

        Retries on transient errors (SSHException, OSError, socket.error) per
        KINDLE_RETRY_ATTEMPTS with exponential backoff. Authentication failures
        are converted to PipelineError(KINDLE_AUTH_FAILED) and NOT retried.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": kindle_config["hostname"],
            "port": kindle_config.get("port", 22),
            "username": kindle_config.get("username", "root"),
            "timeout": KINDLE_SSH_TIMEOUT,
        }

        password = kindle_config.get("password")
        ssh_key_path = kindle_config.get("ssh_key_path")
        if password:
            connect_kwargs["password"] = password
        elif ssh_key_path:
            connect_kwargs["key_filename"] = os.path.expanduser(ssh_key_path)

        try:
            ssh.connect(**connect_kwargs)
        except paramiko.AuthenticationException as e:
            # AuthenticationException is a subclass of SSHException; catch it FIRST
            # so the retry decorator (which catches SSHException) never sees it.
            raise PipelineError(str(e), FailureReason.KINDLE_AUTH_FAILED) from e

        return ssh

    def _get_or_create_ssh(self, kindle_config: dict) -> paramiko.SSHClient:
        """
        Return a live SSH connection for kindle_config["hostname"], reusing
        a pooled connection when its transport is still active. Reconnects
        when the cached connection is stale.
        """
        hostname = kindle_config["hostname"]
        existing = self._ssh_pool.get(hostname)
        if existing is not None:
            transport = existing.get_transport()
            if transport is not None and transport.is_active():
                return existing
            try:
                existing.close()
            except Exception:
                pass
            self._ssh_pool.pop(hostname, None)

        ssh = self._connect_ssh(kindle_config)
        self._ssh_pool[hostname] = ssh
        return ssh

    def close(self) -> None:
        """Close all pooled SSH connections."""
        for ssh in list(self._ssh_pool.values()):
            try:
                ssh.close()
            except Exception:
                pass
        self._ssh_pool.clear()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def is_reachable(self, timeout: float = KINDLE_PROBE_TIMEOUT) -> bool:
        """Cheap TCP probe — is the Kindle awake and accepting connections on the SSH port?

        No SSH handshake: the only question is whether the device is on and
        listening. OSError covers refused connections, timeouts, and DNS
        failures (an unresolvable Tailscale hostname counts as "off").
        """
        try:
            with socket.create_connection((self.hostname, self.port), timeout=timeout):
                return True
        except OSError:
            logger.debug("Kindle %s:%s unreachable: TCP probe failed", self.hostname, self.port)
            return False

    def test_connection(self) -> ConnectionTestResult:
        """
        Test the SSH connection to Kindle.

        Returns:
            ConnectionTestResult with success status and error details
        """
        try:
            ssh = self._create_ssh_client()
            ssh.close()
            logger.info(f"Successfully connected to Kindle at {self.hostname}")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Kindle ({self.hostname})",
            )
        except Exception as e:
            logger.error(f"Kindle SSH connection failed: {e}")
            return classify_ssh_error(e, self.hostname)

    def file_exists(self, remote_path: str) -> bool:
        """
        Check if a file already exists on the Kindle.

        Args:
            remote_path: Path to check on Kindle

        Returns:
            True if file exists, False otherwise
        """
        try:
            ssh = self._create_ssh_client()
            stdin, stdout, stderr = ssh.exec_command(f"test -f {shlex.quote(remote_path)} && echo 'exists'")
            output = stdout.read().decode().strip()
            ssh.close()
            return output == "exists"
        except Exception as e:
            logger.warning(f"Could not check if file exists: {e}")
            return False

    def generate_remote_path(
        self,
        filename: str,
        author: str = "",
        series: str = "",
        folder_organization: str = "flat",
    ) -> str:
        """
        Generate the remote path based on folder organization setting.

        Args:
            filename: The file name to transfer
            author: Author name for organizing by author
            series: Series name for organizing by series
            folder_organization: One of 'flat', 'author', 'series', 'author_series'

        Returns:
            Full remote path including subdirectories
        """

        # Sanitize folder names (remove problematic characters)
        def sanitize(name: str) -> str:
            if not name:
                return ""
            # Remove or replace problematic characters for filesystem
            for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
                name = name.replace(char, "_")
            return name.strip()

        author = sanitize(author)
        series = sanitize(series)

        if folder_organization == "author" and author:
            return f"{self.destination_path}{author}/{filename}"
        elif folder_organization == "series":
            # Use series if available, fall back to author
            folder = series if series else author
            if folder:
                return f"{self.destination_path}{folder}/{filename}"
        elif folder_organization == "author_series":
            if author:
                if series:
                    return f"{self.destination_path}{author}/{series}/{filename}"
                return f"{self.destination_path}{author}/{filename}"

        # Default: flat structure
        return f"{self.destination_path}{filename}"

    def ensure_directory(self, remote_path: str) -> bool:
        """
        Ensure the directory for a remote path exists.

        Args:
            remote_path: Full remote file path

        Returns:
            True if directory exists or was created
        """
        dir_path = os.path.dirname(remote_path)
        if dir_path == self.destination_path.rstrip("/"):
            return True  # Base directory, assume it exists

        try:
            ssh = self._create_ssh_client()
            stdin, stdout, stderr = ssh.exec_command(f'mkdir -p "{dir_path}"')
            exit_status = stdout.channel.recv_exit_status()
            ssh.close()
            if exit_status == 0:
                logger.debug(f"Created directory: {dir_path}")
                return True
            else:
                error = stderr.read().decode().strip()
                logger.warning(f"Failed to create directory {dir_path}: {error}")
                return False
        except Exception as e:
            logger.error(f"Error creating directory: {e}")
            return False

    def transfer_file(
        self,
        local_path: str,
        skip_existing: bool = True,
        author: str = "",
        series: str = "",
        folder_organization: str = "flat",
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict:
        """
        Transfer a file to Kindle via SFTP using atomic write semantics.

        Strategy:
        1. Free-space check via `df` BEFORE transfer (10% margin) → KINDLE_DISK_FULL on shortage.
        2. Upload to `<remote_path>.tmp` (so a partial file never appears at the final path).
        3. Verify .tmp size matches local size; on mismatch → KINDLE_TRANSFER_FAILED + cleanup.
        4. Atomic rename `.tmp` → final path via SSH `mv` (atomic on Kindle ext4 per probe).
        5. On any exception during transfer, attempt best-effort cleanup of the .tmp file.

        Args:
            local_path: Path to local file
            skip_existing: Skip if file already exists on Kindle
            author: Author name for folder organization
            series: Series name for folder organization
            folder_organization: How to organize files ('flat', 'author', 'series', 'author_series')
            progress_callback: Optional callback(bytes_so_far, bytes_total) for progress tracking

        Returns:
            Dictionary with transfer result:
            - success: bool
            - status: 'transferred', 'skipped', 'failed'
            - file_size: int (bytes transferred)
            - error: str (if failed)

        Raises:
            PipelineError(KINDLE_DISK_FULL): Insufficient free space on Kindle.
            PipelineError(KINDLE_TRANSFER_FAILED): Size mismatch or atomic rename failure.
        """
        filename = os.path.basename(local_path)
        remote_path = self.generate_remote_path(filename, author, series, folder_organization)
        remote_tmp = remote_path + ".tmp"

        logger.debug(f"Transfer request: {local_path} -> {remote_path}")

        # Verify local file exists
        if not os.path.exists(local_path):
            logger.error(f"Local file not found: {local_path}")
            return {
                "success": False,
                "status": "failed",
                "error": f"Local file not found: {local_path}",
            }

        local_size = os.path.getsize(local_path)
        ssh = None
        sftp = None

        try:
            ssh = self._create_ssh_client()
            sftp = ssh.open_sftp()

            # Bound every SFTP I/O op so a Kindle sleeping mid-transfer raises
            # socket.timeout instead of hanging the pipeline job forever.
            channel = sftp.get_channel()
            if channel is not None:
                channel.settimeout(KINDLE_TRANSFER_TIMEOUT)

            # Check if file already exists
            if skip_existing and self._file_exists_sftp(ssh, remote_path):
                logger.info(f"File already exists on Kindle, skipping: {filename}")
                return {
                    "success": True,
                    "status": "skipped",
                    "file_size": 0,
                }

            # Ensure directory exists (for folder organization)
            dir_path = os.path.dirname(remote_path)
            if folder_organization != "flat":
                try:
                    sftp.stat(dir_path)
                except OSError:
                    # Directory doesn't exist, create it
                    ssh.exec_command(f'mkdir -p "{dir_path}"')
                    logger.debug(f"Created directory: {dir_path}")

            # Free-space check BEFORE transfer (df reports 1K-blocks on Kindle/POSIX)
            df_target = dir_path or self.destination_path.rstrip("/") or "/mnt/us"
            df_cmd = f"df {shlex.quote(df_target)} | tail -1 | awk '{{print $4}}'"
            _, df_stdout, _ = ssh.exec_command(df_cmd, timeout=KINDLE_SSH_TIMEOUT)
            df_output = df_stdout.read().decode().strip()
            try:
                available_kb = int(df_output) if df_output else 0
            except ValueError:
                available_kb = 0
            available_bytes = available_kb * 1024

            # Require 10% margin to avoid filling the disk to the brim
            required_bytes = int(local_size * 1.1)
            if available_bytes < required_bytes:
                raise PipelineError(
                    f"Insufficient Kindle space: {available_bytes} bytes available, "
                    f"need {required_bytes} (file={local_size}, +10% margin)",
                    FailureReason.KINDLE_DISK_FULL,
                )

            logger.info(f"Uploading (atomic): {filename}")
            try:
                sftp.put(local_path, remote_tmp, callback=progress_callback)
            except Exception:
                try:
                    sftp.remove(remote_tmp)
                except Exception:
                    pass
                raise

            try:
                remote_size = sftp.stat(remote_tmp).st_size
            except Exception as e:
                try:
                    sftp.remove(remote_tmp)
                except Exception:
                    pass
                raise PipelineError(
                    f"Failed to stat remote tmp file after transfer: {e}",
                    FailureReason.KINDLE_TRANSFER_FAILED,
                ) from e

            if remote_size != local_size:
                logger.error(f"File size mismatch: local={local_size}, remote={remote_size}")
                try:
                    sftp.remove(remote_tmp)
                except Exception:
                    pass
                raise PipelineError(
                    f"Transfer size mismatch: local={local_size}, remote={remote_size}",
                    FailureReason.KINDLE_TRANSFER_FAILED,
                )

            # mv is atomic on Kindle ext4 (verified via docs/probes/kindle-rename.md)
            mv_cmd = f"mv {shlex.quote(remote_tmp)} {shlex.quote(remote_path)}"
            _, mv_stdout, mv_stderr = ssh.exec_command(mv_cmd, timeout=KINDLE_SSH_TIMEOUT)
            exit_status = mv_stdout.channel.recv_exit_status()
            if exit_status != 0:
                err = mv_stderr.read().decode().strip()
                try:
                    sftp.remove(remote_tmp)
                except Exception:
                    pass
                raise PipelineError(
                    f"Atomic rename failed (exit={exit_status}): {err}",
                    FailureReason.KINDLE_TRANSFER_FAILED,
                )

            logger.info(f"Successfully transferred: {filename} ({local_size} bytes)")
            return {
                "success": True,
                "status": "transferred",
                "file_size": local_size,
            }

        except PipelineError:
            # Let PipelineError propagate so the pipeline can map it to a failure_reason
            raise
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return {
                "success": False,
                "status": "failed",
                "error": str(e),
            }
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass

    def _file_exists_sftp(self, ssh: paramiko.SSHClient, remote_path: str) -> bool:
        """Check if file exists using existing SSH connection."""
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -f {shlex.quote(remote_path)} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == "exists"
        except Exception:
            return False

    def cleanup_kindle_tmp_files(self, max_age_hours: int = TMP_FILE_MAX_AGE_HOURS) -> int:
        """
        Remove orphan ``.tmp`` files older than ``max_age_hours`` from the Kindle
        destination path. These are leftovers from interrupted atomic transfers.

        Returns:
            Number of .tmp files deleted.
        """
        ssh = None
        try:
            ssh = self._create_ssh_client()
            dest_path = self.destination_path.rstrip("/") or "/mnt/us/books"
            mmin = max_age_hours * 60
            cmd = f"find {shlex.quote(dest_path)} -name '*.tmp' -mmin +{mmin} -delete -print"
            _, stdout, _ = ssh.exec_command(cmd)
            output = stdout.read().decode().strip()
            deleted = [line for line in output.splitlines() if line]
            logger.info(f"Cleaned up {len(deleted)} orphan .tmp files from {dest_path}")
            return len(deleted)
        except Exception as e:
            logger.error(f"Failed to cleanup .tmp files on Kindle: {e}")
            return 0
        finally:
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass

    def list_directory(self, remote_path: str, show_hidden: bool = False, max_entries: int = 1000) -> dict:
        if not remote_path.startswith("/"):
            raise ValueError("Path must be absolute")

        normalized_path = str(PurePosixPath(remote_path))
        effective_max_entries = max(0, min(max_entries, 1000))

        try:
            ssh = self._create_ssh_client()
        except TimeoutError as e:
            raise KindleTimeoutError(str(e)) from e
        except (paramiko.SSHException, OSError) as e:
            raise KindleConnectionError(str(e)) from e

        sftp = None
        try:
            sftp = ssh.open_sftp()
            channel = sftp.get_channel()
            if channel is not None:
                channel.settimeout(10)

            try:
                entries = sftp.listdir_attr(normalized_path)
            except PermissionError as e:
                raise KindlePermissionError(f"Permission denied: {normalized_path}") from e
            except TimeoutError as e:
                raise KindleTimeoutError(str(e)) from e
            except OSError as e:
                errno_value = getattr(e, "errno", None)
                if errno_value in {2, None}:
                    raise KindleNotFoundError(f"Path not found: {normalized_path}") from e
                raise KindleConnectionError(str(e)) from e
            except paramiko.SSHException as e:
                raise KindleConnectionError(str(e)) from e

            browse_entries: list[DirectoryEntry] = []
            for entry in entries:
                if not entry.filename:
                    continue
                if not show_hidden and entry.filename.startswith("."):
                    continue

                full_path = str(PurePosixPath(normalized_path) / entry.filename)
                is_symlink = stat.S_ISLNK(entry.st_mode or 0)

                if is_symlink:
                    try:
                        entry_stat = sftp.stat(full_path)
                    except OSError:
                        browse_entries.append(
                            {
                                "name": entry.filename,
                                "type": "broken_symlink",
                                "is_symlink": True,
                                "size": None,
                            }
                        )
                        continue
                else:
                    entry_stat = entry

                entry_type = "dir" if stat.S_ISDIR(entry_stat.st_mode or 0) else "file"
                browse_entries.append(
                    {
                        "name": entry.filename,
                        "type": entry_type,
                        "is_symlink": is_symlink,
                        "size": None if entry_type == "dir" else entry_stat.st_size,
                    }
                )

            browse_entries.sort(
                key=lambda item: ({"dir": 0, "file": 1, "broken_symlink": 2}[item["type"]], item["name"].lower())
            )
            parent_path = None if normalized_path == "/" else str(PurePosixPath(normalized_path).parent)

            return {
                "current_path": normalized_path,
                "parent_path": parent_path,
                "exists": True,
                "is_dir": True,
                "is_writable": None,
                "entries": browse_entries[:effective_max_entries],
                "truncated": len(browse_entries) > effective_max_entries,
            }
        except TimeoutError as e:
            raise KindleTimeoutError(str(e)) from e
        except paramiko.SSHException as e:
            raise KindleConnectionError(str(e)) from e
        except OSError as e:
            raise KindleConnectionError(str(e)) from e
        finally:
            if sftp is not None:
                sftp.close()
            ssh.close()

    def list_books(self) -> list[dict]:
        """
        List books currently on the Kindle.

        Returns:
            List of file dictionaries with name and size
        """
        try:
            ssh = self._create_ssh_client()
            sftp = ssh.open_sftp()

            files = []
            for entry in sftp.listdir_attr(self.destination_path):
                if entry.filename.lower().endswith((".epub", ".mobi", ".azw", ".azw3", ".pdf")):
                    files.append(
                        {
                            "name": entry.filename,
                            "size": entry.st_size,
                            "modified": entry.st_mtime,
                        }
                    )

            sftp.close()
            ssh.close()

            logger.info(f"Found {len(files)} books on Kindle")
            return files

        except Exception as e:
            logger.error(f"Failed to list books on Kindle: {e}")
            return []

    def delete_file(self, filename: str) -> bool:
        """
        Delete a file from the Kindle.

        Args:
            filename: Name of file to delete

        Returns:
            True if deleted successfully
        """
        remote_path = self.destination_path + filename

        try:
            ssh = self._create_ssh_client()
            sftp = ssh.open_sftp()
            sftp.remove(remote_path)
            sftp.close()
            ssh.close()
            logger.info(f"Deleted file from Kindle: {filename}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")
            return False

    def list_all_books(self, protected_paths: list[str] | None = None) -> list[str]:
        """
        List all books on Kindle recursively, including subdirectories.

        Args:
            protected_paths: List of paths to exclude from listing

        Returns:
            List of full file paths
        """
        protected_paths = protected_paths or []

        try:
            ssh = self._create_ssh_client()

            # Use find command to get all book files recursively
            book_extensions = (
                "\\( -iname '*.epub' -o -iname '*.mobi' -o -iname '*.azw' -o -iname '*.azw3' -o -iname '*.pdf' \\)"
            )
            cmd = f"find {self.destination_path} -type f {book_extensions}"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            output = stdout.read().decode().strip()
            ssh.close()

            files = []
            for line in output.split("\n"):
                if not line:
                    continue
                # Check if path is protected
                is_protected = any(line.startswith(p.rstrip("/")) for p in protected_paths)
                if not is_protected:
                    files.append(line)

            logger.debug(f"Found {len(files)} books on Kindle (recursive)")
            return files

        except Exception as e:
            logger.error(f"Failed to list all books: {e}")
            return []

    def find_orphaned_books(
        self,
        expected_filenames: list[str],
        protected_paths: list[str] | None = None,
    ) -> list[str]:
        """
        Find books on Kindle that are not in the expected list.

        Args:
            expected_filenames: List of filenames that should be on the device
            protected_paths: Paths to exclude from cleanup

        Returns:
            List of full paths to orphaned books
        """
        current_files = self.list_all_books(protected_paths)
        expected_names = {os.path.basename(f) for f in expected_filenames}

        orphans = []
        for filepath in current_files:
            filename = os.path.basename(filepath)
            if filename not in expected_names:
                orphans.append(filepath)

        logger.info(f"Found {len(orphans)} orphaned books on Kindle")
        return orphans

    def delete_book_with_sdr(
        self,
        filepath: str,
        delete_sdr: bool = True,
        ssh: Any | None = None,
    ) -> bool:
        """
        Delete a book file and optionally its .sdr folder.

        Args:
            filepath: Full path to the book file
            delete_sdr: Also delete the .sdr folder for this book
            ssh: Existing SSH client to reuse; when given it is NOT closed here,
                 so bulk callers can hold one connection across many deletions

        Returns:
            True if deletion was successful
        """
        own_ssh = ssh is None
        try:
            if ssh is None:
                ssh = self._create_ssh_client()

            # Delete the book file
            stdin, stdout, stderr = ssh.exec_command(f'rm -f "{filepath}"')
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                error = stderr.read().decode().strip()
                logger.error(f"Failed to delete {filepath}: {error}")
                return False

            logger.info(f"Deleted: {filepath}")

            # Delete .sdr folder if requested
            if delete_sdr:
                # .sdr folder is typically named after the file without extension
                basename = os.path.basename(filepath)
                name_without_ext = os.path.splitext(basename)[0]
                dir_path = os.path.dirname(filepath)
                sdr_path = f"{dir_path}/{name_without_ext}.sdr"

                ssh.exec_command(f'rm -rf "{sdr_path}"')
                logger.debug(f"Removed sdr folder: {sdr_path}")

            return True

        except Exception as e:
            logger.error(f"Error deleting book: {e}")
            raise
        finally:
            if own_ssh and ssh is not None:
                ssh.close()

    def cleanup_orphaned_books(
        self,
        expected_filenames: list[str],
        protected_paths: list[str] | None = None,
        delete_sdr: bool = True,
    ) -> dict:
        """
        Remove all books not in the expected list.

        Holds a single SSH connection for the whole batch (reconnecting once if
        it drops mid-loop) instead of one connection per file.

        Args:
            expected_filenames: Filenames that should remain
            protected_paths: Paths to never delete from
            delete_sdr: Also remove .sdr reading data folders

        Returns:
            Dictionary with cleanup results
        """
        orphans = self.find_orphaned_books(expected_filenames, protected_paths)

        deleted = 0
        failed = 0
        ssh = None
        try:
            if orphans:
                ssh = self._create_ssh_client()
            for filepath in orphans:
                try:
                    ok = self.delete_book_with_sdr(filepath, delete_sdr, ssh=ssh)
                except Exception:
                    # Connection likely dropped — reconnect once and retry this file
                    try:
                        if ssh is not None:
                            ssh.close()
                        ssh = self._create_ssh_client()
                        ok = self.delete_book_with_sdr(filepath, delete_sdr, ssh=ssh)
                    except Exception as e:
                        logger.error(f"Error deleting book after reconnect: {e}")
                        ok = False
                if ok:
                    deleted += 1
                else:
                    failed += 1
        finally:
            if ssh is not None:
                ssh.close()

        logger.info(f"Cleanup complete: {deleted} deleted, {failed} failed")
        return {
            "total_orphans": len(orphans),
            "deleted": deleted,
            "failed": failed,
        }
