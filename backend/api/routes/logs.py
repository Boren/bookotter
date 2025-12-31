"""
Logs API routes.
Provides access to log file contents for the web UI.
"""

import os
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Query

from backend.config import DATA_DIR, load_config

# Project root directory (parent of backend/)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

router = APIRouter()


def tail_file(filepath: str, lines: int = 100) -> list[str]:
    """
    Read the last N lines of a file efficiently.

    Args:
        filepath: Path to the file
        lines: Number of lines to read

    Returns:
        List of log lines
    """
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=lines))
    except Exception:
        return []


def filter_logs_by_level(log_lines: list[str], min_level: str) -> list[str]:
    """
    Filter log lines by minimum log level.

    Args:
        log_lines: List of log lines
        min_level: Minimum level to include (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Filtered list of log lines
    """
    level_priority = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_priority = level_priority.get(min_level.upper(), 0)

    filtered = []
    for line in log_lines:
        # Try to extract level from log line (format: "... - LEVEL - ...")
        for level in level_priority:
            if f" - {level} - " in line:
                if level_priority[level] >= min_priority:
                    filtered.append(line)
                break
        else:
            # If no level found, include line if it's a continuation
            if filtered and (line.startswith(" ") or line.startswith("\t")):
                filtered.append(line)

    return filtered


@router.get("")
async def get_logs(
    lines: int = Query(default=100, ge=1, le=1000, description="Number of lines to return"),
    level: str | None = Query(default=None, description="Minimum log level (DEBUG, INFO, WARNING, ERROR)"),
):
    """
    Get recent log entries.

    Args:
        lines: Number of lines to return (1-1000)
        level: Minimum log level to include

    Returns:
        List of log lines and metadata
    """
    config = load_config()
    log_config = config.get("logging", {})

    # Try multiple log file locations
    log_file = log_config.get("log_file", "bookotter.log")

    # Check in data directory first (Docker volume), then project root, then current directory
    log_path = os.path.join(DATA_DIR, log_file)
    if not os.path.exists(log_path):
        log_path = str(PROJECT_ROOT / log_file)
    if not os.path.exists(log_path):
        log_path = log_file

    # Get log lines
    log_lines = tail_file(log_path, lines)

    # Filter by level if specified
    if level:
        log_lines = filter_logs_by_level(log_lines, level)

    # Get file info
    file_exists = os.path.exists(log_path)
    file_size = os.path.getsize(log_path) if file_exists else 0

    return {
        "lines": [line.rstrip("\n") for line in log_lines],
        "total_lines": len(log_lines),
        "file_path": log_path if file_exists else None,
        "file_size": file_size,
        "available_levels": ["DEBUG", "INFO", "WARNING", "ERROR"],
    }


@router.delete("")
async def clear_logs():
    """
    Clear the log file.

    Returns:
        Success status
    """
    config = load_config()
    log_config = config.get("logging", {})
    log_file = log_config.get("log_file", "bookotter.log")

    # Check in data directory first (Docker volume), then project root, then current directory
    log_path = os.path.join(DATA_DIR, log_file)
    if not os.path.exists(log_path):
        log_path = str(PROJECT_ROOT / log_file)
    if not os.path.exists(log_path):
        log_path = log_file

    if os.path.exists(log_path):
        try:
            with open(log_path, "w") as f:
                f.write("")
            return {"success": True, "message": "Log file cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {"success": True, "message": "Log file does not exist"}
