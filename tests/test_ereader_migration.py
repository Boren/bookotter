"""Tests for the one-shot kindle→ereader migration and its startup guard."""

import json
import sqlite3

import pytest
import yaml

from backend.services.ereader_migration import run_migration

OLD_COLS = [
    "kindle_delivery_status TEXT",
    "kindle_delivery_attempts INTEGER DEFAULT 0",
    "kindle_first_pending_at DATETIME",
    "kindle_delivered_at DATETIME",
    "kindle_pinned BOOLEAN DEFAULT 0",
]


@pytest.fixture
def legacy_data_dir(tmp_path):
    db = tmp_path / "bookotter.db"
    conn = sqlite3.connect(db)
    conn.execute(
        f"CREATE TABLE books (id INTEGER PRIMARY KEY, failure_reason TEXT, failure_history TEXT, {', '.join(OLD_COLS)})"
    )
    conn.execute(
        "INSERT INTO books (id, failure_reason, failure_history, kindle_delivery_status, kindle_pinned) "
        "VALUES (1, 'kindle_unreachable', ?, 'delivered', 1)",
        (json.dumps([{"category": "kindle_unreachable", "message": "Kindle unreachable"}]),),
    )
    conn.commit()
    conn.close()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "kindles": [{"id": "default", "name": "My Kindle", "hostname": "kindle.local"}],
                "pipeline": {"enabled": True, "kindle_sync_on_import": True},
                "kindle_sync": {"enabled": True},
                "hardcover": {"api_token": "tok"},
            }
        )
    )
    return tmp_path


def _columns(data_dir):
    conn = sqlite3.connect(data_dir / "bookotter.db")
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(books)")}
    finally:
        conn.close()


def test_migrates_columns_and_data(legacy_data_dir):
    report = run_migration(legacy_data_dir)
    cols = _columns(legacy_data_dir)
    assert "ereader_pinned" in cols
    assert not any(c.startswith("kindle_") for c in cols)
    conn = sqlite3.connect(legacy_data_dir / "bookotter.db")
    reason, history, status, pinned = conn.execute(
        "SELECT failure_reason, failure_history, ereader_delivery_status, ereader_pinned FROM books WHERE id=1"
    ).fetchone()
    conn.close()
    assert reason == "ereader_unreachable"
    assert json.loads(history)[0]["category"] == "ereader_unreachable"
    assert status == "delivered"
    assert pinned == 1
    assert not report.already_migrated


def test_migrates_config_keys(legacy_data_dir):
    run_migration(legacy_data_dir)
    cfg = yaml.safe_load((legacy_data_dir / "config.yaml").read_text())
    assert cfg["ereaders"][0]["name"] == "My Kindle"  # user values untouched
    assert "kindles" not in cfg
    assert "kindle_sync" not in cfg
    assert cfg["ereader_sync"] == {"enabled": True}
    assert cfg["pipeline"]["ereader_sync_on_import"] is True
    assert "kindle_sync_on_import" not in cfg["pipeline"]
    assert cfg["hardcover"]["api_token"] == "tok"  # unrelated keys preserved


def test_legacy_single_kindle_key(legacy_data_dir):
    cfg_path = legacy_data_dir / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    del cfg["kindles"]
    cfg["kindle"] = {"hostname": "kindle.local"}
    cfg_path.write_text(yaml.safe_dump(cfg))
    run_migration(legacy_data_dir)
    cfg = yaml.safe_load(cfg_path.read_text())
    assert cfg["ereaders"] == [{"id": "default", "name": "E-reader", "hostname": "kindle.local"}]
    assert "kindle" not in cfg


def test_idempotent(legacy_data_dir):
    run_migration(legacy_data_dir)
    report = run_migration(legacy_data_dir)
    assert report.already_migrated
    assert report.actions == []


def test_dry_run_touches_nothing(legacy_data_dir):
    before_db = (legacy_data_dir / "bookotter.db").read_bytes()
    before_cfg = (legacy_data_dir / "config.yaml").read_text()
    report = run_migration(legacy_data_dir, dry_run=True)
    assert report.actions  # would-be actions reported
    assert (legacy_data_dir / "bookotter.db").read_bytes() == before_db
    assert (legacy_data_dir / "config.yaml").read_text() == before_cfg
    assert not (legacy_data_dir / "bookotter.db.bak-ereader").exists()


def test_backups_created(legacy_data_dir):
    run_migration(legacy_data_dir)
    assert (legacy_data_dir / "bookotter.db.bak-ereader").exists()
    assert (legacy_data_dir / "config.yaml.bak-ereader").exists()


def test_existing_backup_blocks_without_force(legacy_data_dir):
    (legacy_data_dir / "bookotter.db.bak-ereader").write_bytes(b"old backup")
    with pytest.raises(FileExistsError):
        run_migration(legacy_data_dir)
    # nothing was changed
    assert "kindle_pinned" in _columns(legacy_data_dir)


def test_half_migrated_resumes(legacy_data_dir):
    conn = sqlite3.connect(legacy_data_dir / "bookotter.db")
    conn.execute('ALTER TABLE books RENAME COLUMN "kindle_pinned" TO "ereader_pinned"')
    conn.commit()
    conn.close()
    report = run_migration(legacy_data_dir)
    cols = _columns(legacy_data_dir)
    assert "kindle_delivery_status" not in cols
    assert "ereader_delivery_status" in cols
    assert not report.already_migrated


def test_fresh_install_noop(tmp_path):
    report = run_migration(tmp_path)
    assert report.already_migrated


def test_init_db_refuses_legacy_columns(legacy_data_dir, monkeypatch):
    from sqlalchemy import create_engine

    import backend.database as database
    from backend.services.ereader_migration import UnmigratedKindleStateError

    engine = create_engine(f"sqlite:///{legacy_data_dir / 'bookotter.db'}")
    monkeypatch.setattr(database, "engine", engine)
    with pytest.raises(UnmigratedKindleStateError, match="migrate-to-ereader"):
        database.init_db()


def test_load_config_refuses_legacy_keys(legacy_data_dir, monkeypatch):
    from backend import config as config_module
    from backend.services.ereader_migration import UnmigratedKindleStateError

    monkeypatch.setenv("BOOKOTTER_CONFIG_PATH", str(legacy_data_dir / "config.yaml"))
    with pytest.raises(UnmigratedKindleStateError, match="migrate-to-ereader"):
        config_module.load_config()


def test_load_config_refuses_nested_legacy_key(legacy_data_dir, monkeypatch):
    from backend import config as config_module
    from backend.services.ereader_migration import UnmigratedKindleStateError

    cfg_path = legacy_data_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"pipeline": {"kindle_sync_on_import": True}}))
    monkeypatch.setenv("BOOKOTTER_CONFIG_PATH", str(cfg_path))
    with pytest.raises(UnmigratedKindleStateError, match="migrate-to-ereader"):
        config_module.load_config()


def test_cli_dry_run(legacy_data_dir, monkeypatch, capsys):
    import sys

    import backend.cli as cli

    monkeypatch.setattr(cli, "DATA_DIR", str(legacy_data_dir))
    monkeypatch.setattr(sys, "argv", ["cli", "migrate-to-ereader", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "would" in capsys.readouterr().out
