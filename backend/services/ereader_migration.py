"""One-shot migration from legacy kindle-* naming to ereader-*.

Runs as `python -m backend.cli migrate-to-ereader` against the data dir.
Uses raw sqlite3/yaml on purpose: it must work against the legacy on-disk
shape regardless of what the current ORM model looks like.
"""

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

COLUMN_RENAMES = {
    "kindle_delivery_status": "ereader_delivery_status",
    "kindle_delivery_attempts": "ereader_delivery_attempts",
    "kindle_first_pending_at": "ereader_first_pending_at",
    "kindle_delivered_at": "ereader_delivered_at",
    "kindle_pinned": "ereader_pinned",
}
CATEGORY_RENAMES = {
    "kindle_unreachable": "ereader_unreachable",
    "kindle_auth_failed": "ereader_auth_failed",
    "kindle_disk_full": "ereader_disk_full",
    "kindle_transfer_failed": "ereader_transfer_failed",
}
CONFIG_KEY_RENAMES = {
    "kindles": "ereaders",
    "kindle_sync": "ereader_sync",
    "kindle_sync_on_import": "ereader_sync_on_import",
}


class UnmigratedKindleStateError(RuntimeError):
    """Legacy Kindle-era data detected; the migrate-to-ereader command must run first."""


@dataclass
class MigrationReport:
    actions: list[str] = field(default_factory=list)
    already_migrated: bool = False


def run_migration(data_dir: Path, *, dry_run: bool = False, force: bool = False) -> MigrationReport:
    data_dir = Path(data_dir)
    db_path = data_dir / "bookotter.db"
    config_path = data_dir / "config.yaml"
    report = MigrationReport()

    db_actions = _plan_db_actions(db_path)
    config_actions, migrated_config = _plan_config_actions(config_path)
    report.actions = db_actions + config_actions
    if not report.actions:
        report.already_migrated = True
        return report
    if dry_run:
        return report

    _backup(db_path, needed=bool(db_actions), force=force)
    _backup(config_path, needed=bool(config_actions), force=force)
    if db_actions:
        _apply_db_migration(db_path)
    if config_actions:
        _atomic_write_yaml(config_path, migrated_config)
    return report


def _plan_db_actions(db_path: Path) -> list[str]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        has_books = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='book'").fetchone()
        if not has_books:
            return []
        cols = {row[1] for row in conn.execute("PRAGMA table_info(book)")}
        actions = [f"rename column book.{old} -> {new}" for old, new in COLUMN_RENAMES.items() if old in cols]
        stale_reasons = sum(
            conn.execute("SELECT COUNT(*) FROM book WHERE failure_reason = ?", (old,)).fetchone()[0]
            for old in CATEGORY_RENAMES
        )
        if stale_reasons:
            actions.append(f"rewrite {stale_reasons} legacy failure_reason value(s)")
        history_rows = 0
        for old in CATEGORY_RENAMES:
            # Escape underscores: in LIKE, a bare `_` matches any character.
            pattern = '%"' + old.replace("_", r"\_") + '"%'
            history_rows += conn.execute(
                "SELECT COUNT(*) FROM book WHERE failure_history LIKE ? ESCAPE '\\'", (pattern,)
            ).fetchone()[0]
        if history_rows:
            actions.append(f"rewrite legacy failure_history categories in {history_rows} row(s)")
        return actions
    finally:
        conn.close()


def _apply_db_migration(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(book)")}
        for old, new in COLUMN_RENAMES.items():
            if old in cols:
                conn.execute(f'ALTER TABLE book RENAME COLUMN "{old}" TO "{new}"')
        for old, new in CATEGORY_RENAMES.items():
            conn.execute("UPDATE book SET failure_reason = ? WHERE failure_reason = ?", (new, old))
            conn.execute(
                "UPDATE book SET failure_history = REPLACE(failure_history, ?, ?) WHERE failure_history LIKE ?",
                (f'"{old}"', f'"{new}"', f'%"{old}"%'),
            )
        conn.commit()
    finally:
        conn.close()


def _plan_config_actions(config_path: Path) -> tuple[list[str], dict]:
    if not config_path.exists():
        return [], {}
    config = yaml.safe_load(config_path.read_text()) or {}
    actions: list[str] = []
    if "kindle" in config and "kindles" not in config and "ereaders" not in config:
        old = config.pop("kindle")
        config["ereaders"] = [{"id": "default", "name": "E-reader", **old}]
        actions.append("fold legacy single 'kindle' key into 'ereaders' list")
    migrated = _rename_keys(config, actions)
    return actions, migrated


def _rename_keys(node, actions: list[str], path: str = ""):
    if isinstance(node, dict):
        renamed = {}
        for key, value in node.items():
            new_key = CONFIG_KEY_RENAMES.get(key, key)
            if new_key != key:
                actions.append(f"rename config key {path}{key} -> {path}{new_key}")
            renamed[new_key] = _rename_keys(value, actions, f"{path}{new_key}.")
        return renamed
    if isinstance(node, list):
        return [_rename_keys(item, actions, path) for item in node]
    return node


def _backup(path: Path, *, needed: bool, force: bool) -> None:
    if not needed:
        return
    backup = path.with_name(path.name + ".bak-ereader")
    if backup.exists() and not force:
        msg = f"{backup} already exists (previous run?). Re-run with --force to overwrite."
        raise FileExistsError(msg)
    shutil.copy2(path, backup)


def _atomic_write_yaml(config_path: Path, config: dict) -> None:
    tmp = config_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
    tmp.rename(config_path)
