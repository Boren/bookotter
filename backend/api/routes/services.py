"""
Service connection test routes.
Handles testing connections to Prowlarr and qBittorrent.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.clients.prowlarr_client import ProwlarrClient
from backend.clients.qbittorrent_client import QBittorrentClient
from backend.config import load_config

router = APIRouter()


class ConnectionTestResult(BaseModel):
    """Response for connection test."""

    success: bool
    message: str | None = None
    error: str | None = None


@router.post("/prowlarr/test")
async def test_prowlarr_connection() -> ConnectionTestResult:
    """Test connection to Prowlarr API using saved credentials."""
    config = load_config()
    prowlarr_config = config.get("prowlarr", {})

    api_key = prowlarr_config.get("api_key")
    base_url = prowlarr_config.get("base_url", "http://localhost:9696")

    if not api_key:
        return ConnectionTestResult(success=False, error="Prowlarr API key not configured")

    try:
        client = ProwlarrClient(
            api_key=api_key,
            base_url=base_url,
        )

        result = client.test_connection()
        return ConnectionTestResult(
            success=result.get("success", False),
            message=result.get("message"),
            error=result.get("error"),
        )

    except Exception as e:
        return ConnectionTestResult(success=False, error=str(e))


@router.post("/qbittorrent/test")
async def test_qbittorrent_connection() -> ConnectionTestResult:
    """Test connection to qBittorrent API using saved credentials."""
    config = load_config()
    qbittorrent_config = config.get("qbittorrent", {})

    username = qbittorrent_config.get("username")
    password = qbittorrent_config.get("password")
    base_url = qbittorrent_config.get("base_url", "http://localhost:8080")

    if not username or not password:
        return ConnectionTestResult(success=False, error="qBittorrent username/password not configured")

    try:
        client = QBittorrentClient(
            username=username,
            password=password,
            base_url=base_url,
        )

        result = client.test_connection()
        return ConnectionTestResult(
            success=result.get("success", False),
            message=result.get("message"),
            error=result.get("error"),
        )

    except Exception as e:
        return ConnectionTestResult(success=False, error=str(e))


@router.get("/prowlarr/indexers")
async def get_prowlarr_indexers() -> dict:
    """Get list of configured indexers from Prowlarr."""
    config = load_config()
    prowlarr_config = config.get("prowlarr", {})

    api_key = prowlarr_config.get("api_key")
    base_url = prowlarr_config.get("base_url", "http://localhost:9696")

    if not api_key:
        return {"success": False, "error": "Prowlarr API key not configured", "indexers": []}

    try:
        client = ProwlarrClient(
            api_key=api_key,
            base_url=base_url,
        )

        indexers = client.get_indexers()
        return {"success": True, "indexers": indexers}

    except Exception as e:
        return {"success": False, "error": str(e), "indexers": []}
