"""Clock helpers."""

from datetime import UTC, datetime


def naive_utcnow() -> datetime:
    """Drop-in replacement for the deprecated datetime.utcnow().

    Returns the current UTC time as a naive datetime. The database schema,
    API isoformat output, and naive/aware comparisons throughout the app all
    assume naive UTC timestamps; switching to aware datetimes is a separate
    migration.
    """
    return datetime.now(UTC).replace(tzinfo=None)
