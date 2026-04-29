"""Helpers for deriving BitTorrent info hashes from magnet/torrent URLs."""

import base64
import binascii
import logging
import re

logger = logging.getLogger(__name__)

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
