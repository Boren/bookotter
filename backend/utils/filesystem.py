import os
from pathlib import Path


def list_local_directory(path: str, show_hidden: bool = False, max_entries: int = 1000) -> dict:
    requested_path = Path(path)
    if not requested_path.is_absolute():
        raise ValueError("Path must be absolute")

    resolved_path = requested_path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(str(resolved_path))
    if not resolved_path.is_dir():
        raise NotADirectoryError(str(resolved_path))

    effective_max_entries = max(0, min(max_entries, 1000))
    entries = []

    for entry in resolved_path.iterdir():
        if not show_hidden and entry.name.startswith("."):
            continue

        is_symlink = entry.is_symlink()
        try:
            entry_stat = entry.stat()
        except OSError:
            # Include dangling symlinks in the listing instead of dropping them silently.
            entries.append(
                {
                    "name": entry.name,
                    "type": "broken_symlink",
                    "is_symlink": is_symlink,
                    "size": None,
                }
            )
            continue

        entry_type = "dir" if entry.is_dir() else "file"
        entries.append(
            {
                "name": entry.name,
                "type": entry_type,
                "is_symlink": is_symlink,
                "size": None if entry_type == "dir" else entry_stat.st_size,
            }
        )

    entries.sort(key=lambda item: ({"dir": 0, "file": 1, "broken_symlink": 2}[item["type"]], item["name"].lower()))

    parent_path = None if resolved_path.parent == resolved_path else str(resolved_path.parent)
    return {
        "current_path": str(resolved_path),
        "parent_path": parent_path,
        "exists": True,
        "is_dir": True,
        "is_writable": os.access(resolved_path, os.W_OK),
        "entries": entries[:effective_max_entries],
        "truncated": len(entries) > effective_max_entries,
    }
