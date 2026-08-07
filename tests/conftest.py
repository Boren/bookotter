"""Pytest configuration and shared fixtures for BookOtter tests."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import blocklist, rss  # noqa: F401 — registers models with Base.metadata

pytest_plugins = [
    "tests.fixtures.mock_clock",
    "tests.fixtures.mock_qbit",
    "tests.fixtures.mock_external",
]


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def test_config():
    """Return a default test configuration matching config.yaml structure."""
    return {
        "hardcover": {
            "api_token": "test_token_12345",
            "api_url": "https://api.hardcover.app/v1/graphql",
        },
        "ereaders": [
            {
                "id": "test_ereader",
                "name": "Test E-reader",
                "hostname": "test.ereader.local",
                "port": 22,
                "username": "root",
                "password": "",
                "ssh_key_path": "/root/.ssh/id_rsa",
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
            "skip_existing": True,
        },
        "logging": {
            "log_file": "bookotter.log",
            "log_level": "INFO",
            "console_output": True,
        },
    }


@pytest.fixture
def tmp_library():
    """Create a temporary directory for library root folder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def tmp_download():
    """Create a temporary directory for downloads."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
