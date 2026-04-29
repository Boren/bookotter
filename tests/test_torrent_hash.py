from backend.services.torrent_hash import extract_info_hash_from_url


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
