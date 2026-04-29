"""Tests for startup config validation."""

from backend.main import validate_config


def make_valid_config():
    return {
        "hardcover": {"api_token": "tok123", "api_url": "https://api.hardcover.app/v1/graphql"},
        "prowlarr": {"api_key": "key123", "base_url": "http://localhost:9696"},
        "qbittorrent": {"password": "pass123", "base_url": "http://localhost:8080", "username": "admin"},
        "kindles": [],
        "library": {"root_folders": []},
    }


class TestValidateConfig:
    def test_valid_config_returns_empty(self):
        cfg = make_valid_config()
        assert validate_config(cfg) == []

    def test_missing_hardcover_api_token(self):
        cfg = make_valid_config()
        cfg["hardcover"]["api_token"] = ""
        errors = validate_config(cfg)
        assert any("hardcover.api_token" in e for e in errors)

    def test_missing_prowlarr_api_key(self):
        cfg = make_valid_config()
        cfg["prowlarr"]["api_key"] = ""
        errors = validate_config(cfg)
        assert any("prowlarr" in e.lower() for e in errors)

    def test_malformed_prowlarr_url(self):
        cfg = make_valid_config()
        cfg["prowlarr"]["base_url"] = "not-a-url"
        errors = validate_config(cfg)
        assert any("prowlarr" in e.lower() for e in errors)

    def test_missing_qbittorrent_password(self):
        cfg = make_valid_config()
        cfg["qbittorrent"]["password"] = ""
        errors = validate_config(cfg)
        assert any("qbittorrent" in e.lower() for e in errors)

    def test_kindle_bad_hostname_is_warning_not_fatal(self):
        cfg = make_valid_config()
        cfg["kindles"] = [{"id": "k1", "hostname": "", "port": 22, "username": "root"}]
        errors = validate_config(cfg)
        assert errors == []
