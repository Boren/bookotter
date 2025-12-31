"""
Kindle SSH/SFTP Client
Handles SSH connections and file transfers to Kindle devices.
"""

import logging
import os
import shlex
from collections.abc import Callable

import paramiko

from backend.clients import ConnectionTestResult, classify_ssh_error

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_config(cls, config: dict) -> "KindleClient":
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

        connect_kwargs = {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "timeout": 10,
        }

        # Use either password or key authentication
        if self.password:
            connect_kwargs["password"] = self.password
        elif self.ssh_key_path:
            key_path = os.path.expanduser(self.ssh_key_path)
            connect_kwargs["key_filename"] = key_path

        ssh.connect(**connect_kwargs)
        return ssh

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
        Transfer a file to Kindle via SFTP.

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
        """
        filename = os.path.basename(local_path)
        remote_path = self.generate_remote_path(filename, author, series, folder_organization)

        logger.debug(f"Transfer request: {local_path} -> {remote_path}")

        # Verify local file exists
        if not os.path.exists(local_path):
            logger.error(f"Local file not found: {local_path}")
            return {
                "success": False,
                "status": "failed",
                "error": f"Local file not found: {local_path}",
            }

        try:
            ssh = self._create_ssh_client()
            sftp = ssh.open_sftp()

            # Check if file already exists
            if skip_existing and self._file_exists_sftp(ssh, remote_path):
                logger.info(f"File already exists on Kindle, skipping: {filename}")
                sftp.close()
                ssh.close()
                return {
                    "success": True,
                    "status": "skipped",
                    "file_size": 0,
                }

            # Ensure directory exists (for folder organization)
            if folder_organization != "flat":
                dir_path = os.path.dirname(remote_path)
                try:
                    sftp.stat(dir_path)
                except OSError:
                    # Directory doesn't exist, create it
                    ssh.exec_command(f'mkdir -p "{dir_path}"')
                    logger.debug(f"Created directory: {dir_path}")

            # Transfer file
            logger.info(f"Uploading: {filename}")
            sftp.put(local_path, remote_path, callback=progress_callback)

            # Verify transfer
            remote_stat = sftp.stat(remote_path)
            local_size = os.path.getsize(local_path)

            sftp.close()
            ssh.close()

            if remote_stat.st_size == local_size:
                logger.info(f"Successfully transferred: {filename} ({local_size} bytes)")
                return {
                    "success": True,
                    "status": "transferred",
                    "file_size": local_size,
                }
            else:
                logger.error(f"File size mismatch: local={local_size}, remote={remote_stat.st_size}")
                return {
                    "success": False,
                    "status": "failed",
                    "error": "File size mismatch after transfer",
                }

        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return {
                "success": False,
                "status": "failed",
                "error": str(e),
            }

    def _file_exists_sftp(self, ssh: paramiko.SSHClient, remote_path: str) -> bool:
        """Check if file exists using existing SSH connection."""
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -f {shlex.quote(remote_path)} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == "exists"
        except Exception:
            return False

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

    def list_all_books(self, protected_paths: list[str] = None) -> list[str]:
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
        protected_paths: list[str] = None,
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
    ) -> bool:
        """
        Delete a book file and optionally its .sdr folder.

        Args:
            filepath: Full path to the book file
            delete_sdr: Also delete the .sdr folder for this book

        Returns:
            True if deletion was successful
        """
        try:
            ssh = self._create_ssh_client()

            # Delete the book file
            stdin, stdout, stderr = ssh.exec_command(f'rm -f "{filepath}"')
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                error = stderr.read().decode().strip()
                logger.error(f"Failed to delete {filepath}: {error}")
                ssh.close()
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

            ssh.close()
            return True

        except Exception as e:
            logger.error(f"Error deleting book: {e}")
            return False

    def cleanup_orphaned_books(
        self,
        expected_filenames: list[str],
        protected_paths: list[str] = None,
        delete_sdr: bool = True,
    ) -> dict:
        """
        Remove all books not in the expected list.

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
        for filepath in orphans:
            if self.delete_book_with_sdr(filepath, delete_sdr):
                deleted += 1
            else:
                failed += 1

        logger.info(f"Cleanup complete: {deleted} deleted, {failed} failed")
        return {
            "total_orphans": len(orphans),
            "deleted": deleted,
            "failed": failed,
        }
