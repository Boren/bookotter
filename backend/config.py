"""
Configuration management for BookOtter.
Handles reading and writing config.yaml with support for multi-Kindle setup.
All configuration (including schedules) is stored in config.yaml as the single source of truth.
"""

import copy
import os
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

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

    # Migrate old single-kindle format to multi-kindle if needed
    file_config = _migrate_kindle_config(file_config)

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


def _migrate_kindle_config(config: dict) -> dict:
    """Migrate old single-kindle config to multi-kindle format."""
    if "kindle" in config and "kindles" not in config:
        # Old format: single kindle object
        old_kindle = config.pop("kindle")
        config["kindles"] = [{"id": "default", "name": "Kindle", **old_kindle}]
    return config


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
        "kindles": [
            {
                "id": "default",
                "name": "Kindle",
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
            "sync_shelves": {  # Hardcover shelves mirrored to the Kindle
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
        },
        "pipeline": {
            "enabled": True,
            "search_on_add": True,  # Auto-search Prowlarr when book added
            "import_on_complete": True,  # Auto-import when download completes
            "kindle_sync_on_import": True,  # Auto-sync to Kindle after import
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
        "schedules": [],
    }


def get_kindle_sync_shelves(config: dict | None = None) -> set[str]:
    """Return the Hardcover shelf names whose books are mirrored to the Kindle."""
    if config is None:
        config = load_config()
    shelves = config.get("transfer", {}).get("sync_shelves", {})
    return {name for name, enabled in shelves.items() if enabled}


def get_kindle_by_id(kindle_id: str) -> dict | None:
    """Get a specific Kindle configuration by ID."""
    config = load_config()
    kindles = config.get("kindles", [])
    for kindle in kindles:
        if kindle.get("id") == kindle_id:
            return kindle
    return None


def get_all_kindles() -> list[dict]:
    """Get all configured Kindles."""
    config = load_config()
    return config.get("kindles", [])


def get_first_real_kindle(config: dict | None = None) -> dict | None:
    """Return the first Kindle config with a non-empty hostname, or None.

    The default config seeds a placeholder Kindle with hostname="" — that
    placeholder is NOT a real device. This helper distinguishes real
    user-configured devices from the default stub. Used to gate automatic
    per-book Kindle delivery (the bulk path takes a kindle_id and is
    unaffected).
    """
    if config is None:
        config = load_config()
    for kindle in config.get("kindles", []):
        if (kindle.get("hostname") or "").strip():
            return kindle
    return None


def get_qbit_category(config: dict | None = None) -> str:
    """Return the configured qBittorrent category label, defaulting to 'books'."""
    if config is None:
        config = load_config()
    return config.get("qbittorrent", {}).get("category", "books")


def add_kindle(kindle: dict) -> dict:
    """Add a new Kindle configuration."""
    config = load_config()
    if "kindles" not in config:
        config["kindles"] = []

    # Ensure ID is unique
    existing_ids = {k.get("id") for k in config["kindles"]}
    if kindle.get("id") in existing_ids:
        raise ValueError(f"Kindle with id '{kindle['id']}' already exists")

    config["kindles"].append(kindle)
    save_config(config)
    return kindle


def update_kindle(kindle_id: str, updates: dict) -> dict | None:
    """Update a Kindle configuration."""
    config = load_config()
    kindles = config.get("kindles", [])

    for i, kindle in enumerate(kindles):
        if kindle.get("id") == kindle_id:
            # Don't allow changing ID
            updates.pop("id", None)
            kindles[i] = {**kindle, **updates}
            save_config(config)
            return kindles[i]

    return None


def delete_kindle(kindle_id: str) -> bool:
    """Delete a Kindle configuration."""
    config = load_config()
    kindles = config.get("kindles", [])

    for i, kindle in enumerate(kindles):
        if kindle.get("id") == kindle_id:
            kindles.pop(i)
            save_config(config)
            return True

    return False


# ============================================================================
# Schedule Configuration Functions
# ============================================================================


def generate_schedule_id(name: str) -> str:
    """Generate a URL-safe schedule ID from name."""
    # Convert to lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "schedule"
    # Append short UUID suffix for uniqueness
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def get_schedules() -> list[dict]:
    """Get all schedules from config."""
    config = load_config()
    return config.get("schedules", [])


def get_schedule_by_id(schedule_id: str) -> dict | None:
    """Get a specific schedule by ID."""
    for schedule in get_schedules():
        if schedule.get("id") == schedule_id:
            return schedule
    return None


def add_schedule(schedule: dict) -> dict:
    """
    Add a new schedule to config.
    Raises ValueError if schedule with same ID already exists.
    """
    config = load_config()
    if "schedules" not in config:
        config["schedules"] = []

    existing_ids = {s.get("id") for s in config["schedules"]}
    if schedule.get("id") in existing_ids:
        raise ValueError(f"Schedule with id '{schedule['id']}' already exists")

    config["schedules"].append(schedule)
    save_config(config)
    return schedule


def update_schedule(schedule_id: str, updates: dict) -> dict | None:
    """
    Update a schedule configuration.
    Returns updated schedule or None if not found.
    """
    config = load_config()
    schedules = config.get("schedules", [])

    for i, schedule in enumerate(schedules):
        if schedule.get("id") == schedule_id:
            # Don't allow changing ID
            updates.pop("id", None)
            schedules[i] = {**schedule, **updates}
            save_config(config)
            return schedules[i]

    return None


def delete_schedule(schedule_id: str) -> bool:
    """
    Delete a schedule configuration.
    Returns True if deleted, False if not found.
    """
    config = load_config()
    schedules = config.get("schedules", [])

    for i, schedule in enumerate(schedules):
        if schedule.get("id") == schedule_id:
            schedules.pop(i)
            save_config(config)
            return True

    return False
