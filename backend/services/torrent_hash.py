"""Helpers for deriving BitTorrent info hashes from magnet/torrent URLs."""

import base64
import binascii
import hashlib
import logging
import os
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

TORRENT_FETCH_TIMEOUT_SECONDS = 30
TORRENT_MAX_BYTES = 10 * 1024 * 1024


def _spool_dir() -> Path:
    data_dir = os.environ.get("BOOKOTTER_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    return Path(data_dir) / "torrents"


def spooled_torrent_path(torrent_hash: str) -> Path | None:
    """Return the spooled .torrent file for a hash, or None if not spooled."""
    if not torrent_hash:
        return None
    path = _spool_dir() / f"{torrent_hash}.torrent"
    return path if path.is_file() else None


def fetch_and_hash_torrent(url: str | None) -> str | None:
    """Download a .torrent file, compute its info hash, and spool the file.

    Used for indexers (typically private trackers behind a Prowlarr proxy) that
    serve .torrent files instead of magnet links. The fetched file is saved to
    the spool dir so qBittorrent can be fed the exact same bytes without a
    second hit on the indexer. Returns the lowercase hex hash, or None.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        response = requests.get(url, timeout=TORRENT_FETCH_TIMEOUT_SECONDS, stream=False)
        response.raise_for_status()
        data = response.content
    except Exception as exc:
        logger.warning("Failed to fetch torrent file from %s: %s", url[:80], exc)
        return None

    if len(data) > TORRENT_MAX_BYTES:
        logger.warning("Torrent file from %s exceeds %d bytes — refusing", url[:80], TORRENT_MAX_BYTES)
        return None

    torrent_hash = compute_info_hash_from_torrent_bytes(data)
    if torrent_hash is None:
        logger.warning("Response from %s is not a valid torrent file", url[:80])
        return None

    try:
        spool = _spool_dir()
        spool.mkdir(parents=True, exist_ok=True)
        (spool / f"{torrent_hash}.torrent").write_bytes(data)
    except OSError as exc:
        logger.warning("Could not spool torrent file for %s: %s", torrent_hash, exc)

    return torrent_hash


_MAGNET_RE = re.compile(r"urn:btih:([a-fA-F0-9]{40}|[A-Z2-7]{32})", re.IGNORECASE)


def extract_info_hash_from_url(url: str | None) -> str | None:
    """Return a normalised lowercase-hex BitTorrent v1 info hash, or None."""
    if not url:
        return None

    match = _MAGNET_RE.search(url)
    if not match:
        return None

    raw_hash = match.group(1)
    if len(raw_hash) == 40:
        return raw_hash.lower()

    try:
        pad_len = (8 - len(raw_hash) % 8) % 8
        padded = raw_hash.upper() + "=" * pad_len
        return binascii.hexlify(base64.b32decode(padded)).decode("ascii")
    except Exception as exc:
        logger.warning("Failed to convert Base32 hash %r to hex: %s", raw_hash, exc)
        return None


def _bencode_skip(data: bytes, pos: int) -> int:
    """Return the index just past the bencoded value starting at ``pos``."""
    lead = data[pos : pos + 1]
    if lead == b"i":
        return data.index(b"e", pos) + 1
    if lead == b"l" or lead == b"d":
        pos += 1
        while data[pos : pos + 1] != b"e":
            pos = _bencode_skip(data, pos)
        return pos + 1
    if lead.isdigit():
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        return colon + 1 + length
    raise ValueError(f"Invalid bencode at offset {pos}")


def compute_info_hash_from_torrent_bytes(data: bytes) -> str | None:
    """Compute the BitTorrent v1 info hash (lowercase hex) from a .torrent file.

    The info hash is the SHA-1 of the raw bencoded ``info`` dict, so the value's
    exact byte span is located without re-encoding. Returns None on malformed
    input or when no top-level ``info`` key exists.
    """
    try:
        if data[0:1] != b"d":
            return None
        pos = 1
        while data[pos : pos + 1] != b"e":
            colon = data.index(b":", pos)
            key_len = int(data[pos:colon])
            key = data[colon + 1 : colon + 1 + key_len]
            pos = colon + 1 + key_len
            end = _bencode_skip(data, pos)
            if key == b"info":
                return hashlib.sha1(data[pos:end]).hexdigest()
            pos = end
        return None
    except (ValueError, IndexError) as exc:
        logger.warning("Failed to parse torrent file for info hash: %s", exc)
        return None
