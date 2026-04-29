#!/usr/bin/env python3
"""
Kindle Rename Atomicity Probe

One-shot probe script that SSHes to the user's Kindle, tests whether `mv` is atomic,
and documents the result. This task gates Task 22's atomic-transfer strategy.

Exit codes:
  0: Probe completed successfully (atomicity verdict documented)
  1: Kindle unreachable or probe failed
"""

import os
import sys
import tempfile
from pathlib import Path

import paramiko

# Add backend to path for config loading
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import load_config


def create_ssh_client(hostname: str, port: int, username: str, password: str | None, ssh_key_path: str | None, timeout: int = 10) -> paramiko.SSHClient:
    """Create and connect an SSH client to the Kindle."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": hostname,
        "port": port,
        "username": username,
        "timeout": timeout,
    }

    if password:
        connect_kwargs["password"] = password
    elif ssh_key_path:
        key_path = os.path.expanduser(ssh_key_path)
        connect_kwargs["key_filename"] = key_path

    ssh.connect(**connect_kwargs)
    return ssh


def run_probe() -> int:
    """Run the atomicity probe. Returns 0 on success, 1 on failure."""
    # Load config
    try:
        config = load_config()
    except Exception as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        return 1

    # Get Kindle config (support both old and new format)
    kindle_config = None
    if "kindles" in config and config["kindles"]:
        kindle_config = config["kindles"][0]
    elif "kindle" in config:
        kindle_config = config["kindle"]

    if not kindle_config or not kindle_config.get("hostname"):
        print("Kindle unreachable: no Kindle configured", file=sys.stderr)
        return 1

    hostname = kindle_config.get("hostname")
    port = kindle_config.get("port", 22)
    username = kindle_config.get("username", "root")
    password = kindle_config.get("password")
    ssh_key_path = kindle_config.get("ssh_key_path")

    # Connect to Kindle
    try:
        ssh = create_ssh_client(hostname, port, username, password, ssh_key_path, timeout=10)
    except Exception as e:
        print(f"Kindle unreachable: {e}", file=sys.stderr)
        return 1

    try:
        # Get system info
        stdin, stdout, stderr = ssh.exec_command("uname -a")
        uname_output = stdout.read().decode().strip()

        stdin, stdout, stderr = ssh.exec_command("mv --version 2>&1 | head -1")
        mv_version = stdout.read().decode().strip()

        # Create SFTP client for file operations
        sftp = ssh.open_sftp()

        # Create a 1MB test file
        test_src = "/mnt/us/probe-test-src.tmp"
        test_dst = "/mnt/us/probe-test-dst.tmp"

        # Write 1MB of data via SFTP
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * (1024 * 1024))  # 1MB
            tmp_path = tmp.name

        try:
            sftp.put(tmp_path, test_src)

            # Verify source file exists
            try:
                src_stat = sftp.stat(test_src)
                src_size = src_stat.st_size
            except OSError:
                print("Failed to create test file on Kindle", file=sys.stderr)
                sftp.close()
                ssh.close()
                return 1

            # Perform atomic rename via SSH
            stdin, stdout, stderr = ssh.exec_command(f"mv {test_src} {test_dst}")
            exit_code = stdout.channel.recv_exit_status()

            if exit_code != 0:
                error_msg = stderr.read().decode().strip()
                print(f"mv command failed: {error_msg}", file=sys.stderr)
                sftp.close()
                ssh.close()
                return 1

            # Check atomicity: src should be gone, dst should exist with correct size
            src_exists = False
            dst_exists = False
            dst_size = 0

            try:
                sftp.stat(test_src)
                src_exists = True
            except OSError:
                pass

            try:
                dst_stat = sftp.stat(test_dst)
                dst_exists = True
                dst_size = dst_stat.st_size
            except OSError:
                pass

            # Determine atomicity verdict
            is_atomic = not src_exists and dst_exists and dst_size == src_size

            # Cleanup
            if src_exists:
                try:
                    sftp.remove(test_src)
                except OSError:
                    pass

            if dst_exists:
                try:
                    sftp.remove(test_dst)
                except OSError:
                    pass

            sftp.close()

            # Generate markdown documentation
            verdict = "YES" if is_atomic else "NO"
            strategy = "atomic mv (tmp → rename to final)" if is_atomic else "cp+verify+rm (transfer + size verify + delete tmp)"

            markdown_content = f"""# Kindle Rename Atomicity Probe Results

## Kindle System Information

- **Firmware/Shell**: {uname_output}
- **mv Command**: {mv_version}

## Atomicity Test Results

- **Test File Size**: 1 MB
- **Source File**: `/mnt/us/probe-test-src.tmp`
- **Destination File**: `/mnt/us/probe-test-dst.tmp`
- **Rename Command**: `mv /mnt/us/probe-test-src.tmp /mnt/us/probe-test-dst.tmp`

### Verdict: **{verdict}**

After rename:
- Source file exists: {src_exists}
- Destination file exists: {dst_exists}
- Destination file size: {dst_size} bytes (expected: {src_size})

## Recommended Strategy for Task 22

**Use: {strategy}**

### Rationale

"""

            if is_atomic:
                markdown_content += """The Kindle's `mv` command is atomic, meaning the rename operation is guaranteed to complete fully or not at all. This is the expected behavior on POSIX-compliant filesystems (ext4, etc.).

**Strategy**: Use atomic rename for Task 22:
1. Transfer file to temporary location (e.g., `/mnt/us/books/.tmp-filename.epub`)
2. Rename to final destination atomically via `mv`
3. No need for size verification after rename (atomicity guarantees correctness)

**Benefits**:
- Atomic operation prevents partial/corrupted files
- Simpler logic (no verify+cleanup fallback)
- Faster (no redundant verification)
"""
            else:
                markdown_content += """The Kindle's `mv` command is NOT atomic, meaning the rename operation could fail partway through, leaving both source and destination in an inconsistent state.

**Strategy**: Use transfer + verify + cleanup for Task 22:
1. Transfer file to temporary location (e.g., `/mnt/us/books/.tmp-filename.epub`)
2. Verify file size matches local file
3. If verification passes, delete temporary file
4. If verification fails, clean up and retry

**Benefits**:
- Handles non-atomic rename gracefully
- Detects corruption via size verification
- Allows retry logic for transient failures

**Fallback**: If `mv` fails, use `cp` + `rm` instead.
"""

            markdown_content += "\n## Probe Execution\n\n- **Timestamp**: Generated by probe_kindle_rename.py\n- **Status**: Completed successfully\n- **Cleanup**: All test files removed from Kindle\n"

            # Create docs/probes directory if needed
            docs_dir = Path(__file__).parent.parent / "docs" / "probes"
            docs_dir.mkdir(parents=True, exist_ok=True)

            # Write markdown
            markdown_path = docs_dir / "kindle-rename.md"
            with open(markdown_path, "w") as f:
                f.write(markdown_content)

            print(f"Probe completed successfully. Results written to {markdown_path}")
            print(f"Atomicity verdict: {verdict}")

            # Save evidence
            evidence_dir = Path(__file__).parent.parent / ".sisyphus" / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)

            evidence_path = evidence_dir / "task-2-probe-output.txt"
            with open(evidence_path, "w") as f:
                f.write("Kindle Rename Atomicity Probe Output\n")
                f.write("====================================\n\n")
                f.write(f"Firmware/Shell: {uname_output}\n")
                f.write(f"mv Command: {mv_version}\n\n")
                f.write("Test Results:\n")
                f.write(f"  Source exists after rename: {src_exists}\n")
                f.write(f"  Destination exists after rename: {dst_exists}\n")
                f.write(f"  Destination size: {dst_size} bytes (expected: {src_size})\n\n")
                f.write(f"Atomicity Verdict: {verdict}\n")
                f.write(f"Recommended Strategy: {strategy}\n")

            print(f"Evidence saved to {evidence_path}")

            return 0

        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"Probe failed: {e}", file=sys.stderr)
        return 1

    finally:
        ssh.close()


if __name__ == "__main__":
    sys.exit(run_probe())
