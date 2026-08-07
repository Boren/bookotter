"""
Configuration management for BookOtter.
Handles reading and writing config.yaml with support for multi-E-reader setup.
All configuration is stored in config.yaml as the single source of truth.
"""

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from backend.utils.naming import DEFAULT_NAMING_TEMPLATE

# Sensitive fields that should be masked in API responses
SENSITIVE_FIELDS = {"api_token", "api_key", "password"}

# Default data directory
DATA_DIR = os.environ.get("BOOKOTTER_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))


def get_config_path() -> Path:
    """Get the path to config.yaml, checking multiple locations."""
    # Priority order:
    # 1. Environment variable
    # 2. data/config.yaml (Docker mount point)
    # 3. ./config.yaml (current directory)

    env_path = os.environ.get("BOOKOTTER_CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        return Path(env_path)

    data_config = Path(DATA_DIR) / "config.yaml"
    if data_config.exists():
        return data_config

    local_config = Path("config.yaml")
    if local_config.exists():
        return local_config

    # Default to data directory for new installations
    return data_config


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base dict, with updates taking priority."""
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """Load configuration from config.yaml, merged with defaults."""
    config_path = get_config_path()

    if not config_path.exists():
        return get_default_config()

    with open(config_path) as f:
        file_config = yaml.safe_load(f) or {}

    # Legacy cron schedules were replaced by the ereader_sync toggle; drop the
    # stale list so it stays inert and disappears on the next save.
    file_config.pop("schedules", None)

    # Merge file config into defaults so new sections are always present
    return _deep_merge(get_default_config(), file_config)


def save_config(config: dict) -> None:
    """
    Save configuration to config.yaml atomically.
    Uses temp file + rename pattern to prevent corruption on concurrent writes.
    """
    config_path = get_config_path()

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first
    temp_path = config_path.with_suffix(".yaml.tmp")
    with open(temp_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())  # Ensure data is on disk

    # Atomic rename (POSIX guarantees atomicity)
    temp_path.rename(config_path)


def mask_sensitive_data(config: dict) -> dict:
    """Return a copy of config with sensitive fields masked."""
    masked = copy.deepcopy(config)

    def _mask_recursive(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: "***MASKED***" if k in SENSITIVE_FIELDS and v else _mask_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_mask_recursive(item) for item in obj]
        return obj

    return _mask_recursive(masked)


def update_config(updates: dict) -> dict:
    """
    Update configuration with partial updates.
    Merges updates into existing config and saves.
    """
    config = load_config()

    def _remove_masked(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _remove_masked(v) for k, v in obj.items() if v != "***MASKED***"}
        elif isinstance(obj, list):
            return [_remove_masked(item) for item in obj]
        return obj

    updates = _remove_masked(updates)
    config = _deep_merge(config, updates)

    save_config(config)
    return config


def get_default_config() -> dict:
    """Return default configuration structure."""
    return {
        "hardcover": {
            "api_token": "",
            "api_url": "https://api.hardcover.app/v1/graphql",
        },
        "prowlarr": {
            "api_key": "",
            "base_url": "http://localhost:9696",
        },
        "qbittorrent": {
            "base_url": "http://localhost:8080",
            "username": "admin",
            "password": "",
            "category": "books",
        },
        "ereaders": [
            {
                "id": "default",
                "name": "E-reader",
                "hostname": "",
                "port": 22,
                "username": "root",
                "password": "",
                "ssh_key_path": "~/.ssh/id_rsa",
                "destination_path": "/mnt/us/books/",
            }
        ],
        "matching": {
            "use_isbn": True,
            "use_fuzzy": True,
            "fuzzy_threshold": 80,
        },
        "sync": {
            "include_statuses": {
                "want_to_read": True,
                "currently_reading": False,
                "read": False,
            }
        },
        "transfer": {
            "dry_run": False,
            "folder_organization": "flat",  # flat, author, series, author_series
            "sync_shelves": {  # Hardcover shelves mirrored to the E-reader
                "want_to_read": True,
                "currently_reading": True,
                "read": False,
            },
            "cleanup_enabled": True,  # Mirror mode: delete device books not on synced shelves or pinned
            "cleanup_sdr_folders": True,  # Also remove .sdr reading data
            "cleanup_protected_paths": [],  # Paths to never delete from
        },
        "library": {
            "root_folders": [],  # [{path, name, folder_organization}]
            "download_path": "",  # For display only — qBit manages actual paths
            "naming_template": DEFAULT_NAMING_TEMPLATE,  # Filename template for library epubs
        },
        "pipeline": {
            "enabled": True,
            "search_on_add": True,  # Auto-search Prowlarr when book added
            "import_on_complete": True,  # Auto-import when download completes
            "ereader_sync_on_import": True,  # Auto-sync to E-reader after import
            "status_actions": {
                "want_to_read": {"download": True},
                "currently_reading": {"download": True},
                "read": {"download": True},
            },
        },
        "rss": {
            "enabled": False,
            "cron_expression": "*/15 * * * *",
            "max_age_days": 3,
            "limit": 100,
            "cleanup_retention_days": 60,
            "caps_cache_seconds": 3600,
        },
        "logging": {
            "log_file": "bookotter.log",
            "log_level": "INFO",
            "console_output": True,
        },
        "ereader_sync": {
            "enabled": False,
            "interval_hours": 1,  # 1 | 6 | 24
        },
    }


def get_ereader_sync_shelves(config: dict | None = None) -> set[str]:
    """Return the Hardcover shelf names whose books are mirrored to the E-reader."""
    if config is None:
        config = load_config()
    shelves = config.get("transfer", {}).get("sync_shelves", {})
    return {name for name, enabled in shelves.items() if enabled}


def get_ereader_by_id(ereader_id: str) -> dict | None:
    """Get a specific E-reader configuration by ID."""
    config = load_config()
    ereaders = config.get("ereaders", [])
    for ereader in ereaders:
        if ereader.get("id") == ereader_id:
            return ereader
    return None


def get_all_ereaders() -> list[dict]:
    """Get all configured E-readers."""
    config = load_config()
    return config.get("ereaders", [])


def get_first_real_ereader(config: dict | None = None) -> dict | None:
    """Return the first E-reader config with a non-empty hostname, or None.

    The default config seeds a placeholder E-reader with hostname="" — that
    placeholder is NOT a real device. This helper distinguishes real
    user-configured devices from the default stub. Used to gate automatic
    per-book E-reader delivery (the bulk path takes a ereader_id and is
    unaffected).
    """
    if config is None:
        config = load_config()
    for ereader in config.get("ereaders", []):
        if (ereader.get("hostname") or "").strip():
            return ereader
    return None


def get_qbit_category(config: dict | None = None) -> str:
    """Return the configured qBittorrent category label, defaulting to 'books'."""
    if config is None:
        config = load_config()
    return config.get("qbittorrent", {}).get("category", "books")


def add_ereader(ereader: dict) -> dict:
    """Add a new E-reader configuration."""
    config = load_config()
    if "ereaders" not in config:
        config["ereaders"] = []

    # Ensure ID is unique
    existing_ids = {k.get("id") for k in config["ereaders"]}
    if ereader.get("id") in existing_ids:
        raise ValueError(f"E-reader with id '{ereader['id']}' already exists")

    config["ereaders"].append(ereader)
    save_config(config)
    return ereader


def update_ereader(ereader_id: str, updates: dict) -> dict | None:
    """Update a E-reader configuration."""
    config = load_config()
    ereaders = config.get("ereaders", [])

    for i, ereader in enumerate(ereaders):
        if ereader.get("id") == ereader_id:
            # Don't allow changing ID
            updates.pop("id", None)
            ereaders[i] = {**ereader, **updates}
            save_config(config)
            return ereaders[i]

    return None


def delete_ereader(ereader_id: str) -> bool:
    """Delete a E-reader configuration."""
    config = load_config()
    ereaders = config.get("ereaders", [])

    for i, ereader in enumerate(ereaders):
        if ereader.get("id") == ereader_id:
            ereaders.pop(i)
            save_config(config)
            return True

    return False
