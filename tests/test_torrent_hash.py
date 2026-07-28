from unittest.mock import MagicMock

from backend.services.torrent_hash import (
    compute_info_hash_from_torrent_bytes,
    extract_info_hash_from_url,
    fetch_and_hash_torrent,
    spooled_torrent_path,
)


class TestExtractInfoHashFromUrl:
    def test_40hex_returns_lowercase(self):
        url = "magnet:?xt=urn:btih:AABBCCDD11223344AABBCCDD11223344AABBCCDD&dn=Test"
        assert extract_info_hash_from_url(url) == "aabbccdd11223344aabbccdd11223344aabbccdd"

    def test_base32_returns_40hex(self):
        url = "magnet:?xt=urn:btih:ABCDEFABCDEFABCDEFABCDEFABCDEFAB&dn=Test"
        result = extract_info_hash_from_url(url)
        assert result is not None
        assert len(result) == 40
        assert result == result.lower()

    def test_no_btih_returns_none(self):
        assert extract_info_hash_from_url("https://example.com/torrent/file.torrent") is None

    def test_none_returns_none(self):
        assert extract_info_hash_from_url(None) is None

    def test_empty_string_returns_none(self):
        assert extract_info_hash_from_url("") is None

    def test_mixed_case_normalised_to_lowercase(self):
        url = "magnet:?xt=urn:btih:AaBbCcDd1122334455AaBbCcDd1122334455AaBb&dn=Test"
        result = extract_info_hash_from_url(url)
        assert result == "aabbccdd1122334455aabbccdd1122334455aabb"


def _bencode(obj) -> bytes:
    """Minimal bencoder for building test fixtures."""
    if isinstance(obj, int):
        return b"i" + str(obj).encode() + b"e"
    if isinstance(obj, bytes):
        return str(len(obj)).encode() + b":" + obj
    if isinstance(obj, str):
        return _bencode(obj.encode())
    if isinstance(obj, list):
        return b"l" + b"".join(_bencode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in obj.items())
        return b"d" + b"".join(_bencode(k) + _bencode(v) for k, v in items) + b"e"
    raise TypeError(obj)


def _make_torrent(name="test.epub", length=12345) -> bytes:
    return _bencode(
        {
            "announce": "https://tracker.example/announce",
            "info": {"name": name, "length": length, "piece length": 16384, "pieces": b"\x00" * 20},
        }
    )


class TestComputeInfoHashFromTorrentBytes:
    def test_returns_sha1_of_info_dict(self):
        import hashlib

        torrent = _make_torrent()
        info_bencoded = _bencode({"name": "test.epub", "length": 12345, "piece length": 16384, "pieces": b"\x00" * 20})
        expected = hashlib.sha1(info_bencoded).hexdigest()

        assert compute_info_hash_from_torrent_bytes(torrent) == expected

    def test_hash_is_40_char_lowercase_hex(self):
        result = compute_info_hash_from_torrent_bytes(_make_torrent())
        assert result is not None
        assert len(result) == 40
        assert result == result.lower()

    def test_different_info_gives_different_hash(self):
        a = compute_info_hash_from_torrent_bytes(_make_torrent(name="a.epub"))
        b = compute_info_hash_from_torrent_bytes(_make_torrent(name="b.epub"))
        assert a != b

    def test_invalid_data_returns_none(self):
        assert compute_info_hash_from_torrent_bytes(b"not a torrent") is None

    def test_missing_info_key_returns_none(self):
        assert compute_info_hash_from_torrent_bytes(_bencode({"announce": "x"})) is None

    def test_empty_returns_none(self):
        assert compute_info_hash_from_torrent_bytes(b"") is None


class TestFetchAndHashTorrent:
    def test_fetches_hashes_and_spools(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        torrent = _make_torrent()
        expected = compute_info_hash_from_torrent_bytes(torrent)

        response = MagicMock()
        response.content = torrent
        response.raise_for_status = MagicMock()
        monkeypatch.setattr("backend.services.torrent_hash.requests.get", MagicMock(return_value=response))

        result = fetch_and_hash_torrent("http://indexer.example/download?id=1")

        assert result == expected
        spooled = tmp_path / "torrents" / f"{expected}.torrent"
        assert spooled.exists()
        assert spooled.read_bytes() == torrent

    def test_network_error_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(
            "backend.services.torrent_hash.requests.get",
            MagicMock(side_effect=Exception("connection refused")),
        )

        assert fetch_and_hash_torrent("http://indexer.example/download?id=1") is None

    def test_non_torrent_response_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        response = MagicMock()
        response.content = b"<html>login required</html>"
        response.raise_for_status = MagicMock()
        monkeypatch.setattr("backend.services.torrent_hash.requests.get", MagicMock(return_value=response))

        assert fetch_and_hash_torrent("http://indexer.example/download?id=1") is None

    def test_non_http_url_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        assert fetch_and_hash_torrent("magnet:?xt=urn:btih:" + "a" * 40) is None


class TestSpooledTorrentPath:
    def test_returns_path_when_spooled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        spool = tmp_path / "torrents"
        spool.mkdir()
        (spool / ("b" * 40 + ".torrent")).write_bytes(b"x")

        path = spooled_torrent_path("b" * 40)
        assert path is not None
        assert path.name == "b" * 40 + ".torrent"

    def test_returns_none_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOKOTTER_DATA_DIR", str(tmp_path))
        assert spooled_torrent_path("c" * 40) is None
