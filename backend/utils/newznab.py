"""
Newznab/Prowlarr RSS XML parsing utilities.

Pure functions that parse Newznab-compatible XML responses (caps and RSS feeds)
into normalized Python dicts. Uses only the stdlib `xml.etree.ElementTree` —
no third-party XML or RSS libraries.

The output format of `parse_rss_xml` matches the normalized dict shape produced
by `ProwlarrClient._normalize_result` so downstream consumers can treat both
sources interchangeably.
"""

from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

TORZNAB_NS = "http://torznab.com/schemas/2015/feed"
_TORZNAB_ATTR = f"{{{TORZNAB_NS}}}attr"

ET.register_namespace("torznab", TORZNAB_NS)


def _safe_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except ValueError, TypeError:
        return default


def _collect_torznab_attrs(item: ET.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for attr in item.findall(_TORZNAB_ATTR):
        name = attr.get("name")
        value = attr.get("value")
        if name is None or value is None:
            continue
        attrs[name] = value
    return attrs


def _collect_categories(item: ET.Element) -> list[dict]:
    seen: set[int] = set()
    categories: list[dict] = []

    for cat_el in item.findall("category"):
        text = (cat_el.text or "").strip()
        if not text:
            continue
        try:
            cat_id = int(text)
        except ValueError:
            continue
        if cat_id in seen:
            continue
        seen.add(cat_id)
        categories.append({"id": cat_id})

    for attr in item.findall(_TORZNAB_ATTR):
        if attr.get("name") != "category":
            continue
        value = attr.get("value")
        if value is None:
            continue
        try:
            cat_id = int(value.strip())
        except ValueError:
            continue
        if cat_id in seen:
            continue
        seen.add(cat_id)
        categories.append({"id": cat_id})

    return categories


def _extract_download_url(item: ET.Element) -> str | None:
    link_el = item.find("link")
    if link_el is not None and link_el.text and link_el.text.strip():
        return link_el.text.strip()

    enclosure = item.find("enclosure")
    if enclosure is not None:
        url = enclosure.get("url")
        if url and url.strip():
            return url.strip()

    return None


def _extract_size(item: ET.Element, torznab_attrs: dict[str, str]) -> int:
    if "size" in torznab_attrs:
        return _safe_int(torznab_attrs["size"], default=0)

    size_el = item.find("size")
    if size_el is not None:
        return _safe_int(size_el.text, default=0)

    return 0


def parse_caps_xml(xml_text: str) -> dict:
    """Parse a Newznab/Torznab capabilities XML document.

    Returns a dict with::

        {
            "book_search_supported": bool,
            "categories": list[int],
        }

    Any parse error is logged and a safe default is returned. The function never
    raises.
    """
    default: dict = {"book_search_supported": False, "categories": []}

    if not xml_text or not xml_text.strip():
        logger.warning("parse_caps_xml: received empty XML payload")
        return default

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("parse_caps_xml: failed to parse caps XML: %s", exc)
        return default

    book_search_supported = False
    try:
        searching = root.find("searching")
        if searching is not None:
            book_search = searching.find("book-search")
            if book_search is not None:
                # Prowlarr emits ``available="yes"``; Newznab spec says ``supported="yes"``. Accept either.
                supported_attr = (book_search.get("supported") or "").strip().lower()
                available_attr = (book_search.get("available") or "").strip().lower()
                book_search_supported = supported_attr == "yes" or available_attr == "yes"
    except Exception as exc:  # noqa: BLE001
        logger.warning("parse_caps_xml: error inspecting <searching>: %s", exc)
        return default

    categories: list[int] = []
    try:
        categories_el = root.find("categories")
        if categories_el is not None:
            for cat in categories_el.findall("category"):
                cat_id = _safe_int(cat.get("id"), default=-1)
                if cat_id >= 0:
                    categories.append(cat_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("parse_caps_xml: error inspecting <categories>: %s", exc)
        return {"book_search_supported": book_search_supported, "categories": []}

    return {"book_search_supported": book_search_supported, "categories": categories}


def parse_rss_xml(xml_text: str, indexer_id: int, indexer_name: str) -> list[dict]:
    """Parse a Newznab/Torznab RSS feed into normalized result dicts.

    The output dicts match the shape produced by
    ``ProwlarrClient._normalize_result`` and contain exactly these 12 keys:

        guid, indexer_id, indexer, title, size, seeders, leechers,
        download_url, magnet_url, categories, protocol, publish_date

    Items are skipped (silently dropped from the result list) when any of these
    is true:

      - ``<guid>`` is missing or empty after stripping/trailing-slash removal
      - ``<pubDate>`` is missing or fails RFC822 parsing
      - both ``<link>`` and ``<enclosure url>`` are missing/empty

    On any error parsing the document as a whole, a warning is logged and an
    empty list is returned. The function never raises.
    """
    if not xml_text or not xml_text.strip():
        logger.warning("parse_rss_xml: received empty XML payload from indexer %s", indexer_name)
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("parse_rss_xml: failed to parse RSS XML from indexer %s: %s", indexer_name, exc)
        return []

    channel = root.find("channel")
    items_root = channel if channel is not None else root

    results: list[dict] = []
    for item in items_root.findall("item"):
        try:
            normalized = _normalize_item(item, indexer_id=indexer_id, indexer_name=indexer_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("parse_rss_xml: skipping malformed <item> from %s: %s", indexer_name, exc)
            continue
        if normalized is not None:
            results.append(normalized)

    return results


def _normalize_item(item: ET.Element, *, indexer_id: int, indexer_name: str) -> dict | None:
    guid_el = item.find("guid")
    raw_guid = (guid_el.text or "") if guid_el is not None else ""
    guid = raw_guid.strip().rstrip("/")
    if not guid:
        return None

    pubdate_el = item.find("pubDate")
    pubdate_text = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
    if not pubdate_text:
        return None
    try:
        publish_dt = parsedate_to_datetime(pubdate_text)
    except TypeError, ValueError:
        return None
    if publish_dt is None:
        return None
    publish_date = publish_dt.isoformat()

    download_url = _extract_download_url(item)
    if not download_url:
        return None

    title_el = item.find("title")
    title = title_el.text.strip() if (title_el is not None and title_el.text) else None

    torznab_attrs = _collect_torznab_attrs(item)

    seeders = _safe_int(torznab_attrs.get("seeders"), default=0)
    # `peers` in torznab encodes the leecher count.
    leechers = _safe_int(torznab_attrs.get("peers"), default=0)
    size = _extract_size(item, torznab_attrs)

    magnet_value = torznab_attrs.get("magneturl")
    magnet_url = magnet_value.strip() if magnet_value and magnet_value.strip() else None

    categories = _collect_categories(item)

    return {
        "guid": guid,
        "indexer_id": indexer_id,
        "indexer": indexer_name,
        "title": title,
        "size": size,
        "seeders": seeders,
        "leechers": leechers,
        "download_url": download_url,
        "magnet_url": magnet_url,
        "categories": categories,
        "protocol": "torrent",
        "publish_date": publish_date,
    }
