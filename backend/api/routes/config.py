"""
Configuration API routes.
Handles reading and updating config.yaml, and testing service connections.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.clients.hardcover_client import HardcoverClient
from backend.clients.kindle_client import KindleClient
from backend.config import load_config, mask_sensitive_data, update_config
from backend.utils.naming import validate_template

router = APIRouter()


class ConfigUpdate(BaseModel):
    """Request body for configuration updates."""

    config: dict[str, Any]


class ConnectionTestResult(BaseModel):
    """Response for connection test."""

    success: bool
    message: str | None = None
    error: str | None = None


class HardcoverTestRequest(BaseModel):
    """Request body for testing Hardcover connection with UI values."""

    api_token: str | None = None
    api_url: str | None = None


@router.get("")
async def get_config():
    """
    Get the current configuration.
    Sensitive fields (api_key, api_token, password) are masked.
    """
    config = load_config()
    return mask_sensitive_data(config)


@router.put("")
async def update_config_endpoint(body: ConfigUpdate):
    """
    Update the configuration.
    Masked values (***MASKED***) are ignored and not written.
    """
    naming_template = body.config.get("library", {}).get("naming_template")
    if naming_template is not None:
        errors = validate_template(naming_template)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))

    try:
        updated = update_config(body.config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Re-register the automatic Kindle sync job so toggling the setting takes
    # effect without a restart. Guarded on the key so unrelated saves don't
    # touch the scheduler.
    if "kindle_sync" in body.config:
        from backend.api.routes.sync import apply_kindle_sync_schedule

        apply_kindle_sync_schedule(updated)

    return {"success": True, "config": mask_sensitive_data(updated)}


@router.post("/test/hardcover")
async def test_hardcover_connection(request: HardcoverTestRequest | None = None) -> ConnectionTestResult:
    """Test connection to Hardcover API using provided or saved credentials."""
    config = load_config()
    hardcover_config = config.get("hardcover", {})

    # Use request values if provided, otherwise fall back to saved config
    api_token = (request.api_token if request else None) or hardcover_config.get("api_token")
    api_url = (request.api_url if request else None) or hardcover_config.get(
        "api_url", "https://api.hardcover.app/v1/graphql"
    )

    if not api_token:
        return ConnectionTestResult(success=False, error="API token not configured")

    try:
        client = HardcoverClient(
            api_token=api_token,
            api_url=api_url,
        )

        result = client.test_connection()
        return ConnectionTestResult(
            success=result.get("success", False),
            message=result.get("message"),
            error=result.get("error"),
        )

    except Exception as e:
        return ConnectionTestResult(success=False, error=str(e))


@router.post("/test/kindle/{kindle_id}")
async def test_kindle_connection(kindle_id: str) -> ConnectionTestResult:
    """Test SSH connection to a specific Kindle."""
    config = load_config()
    kindles = config.get("kindles", [])

    # Find the kindle by ID
    kindle_config = None
    for k in kindles:
        if k.get("id") == kindle_id:
            kindle_config = k
            break

    if not kindle_config:
        return ConnectionTestResult(success=False, error=f"Kindle '{kindle_id}' not found")

    if not kindle_config.get("hostname"):
        return ConnectionTestResult(success=False, error="Hostname not configured")

    try:
        client = KindleClient.from_config(kindle_config)
        result = client.test_connection()

        if result["success"]:
            return ConnectionTestResult(success=True, message=result.get("message"))
        else:
            return ConnectionTestResult(success=False, error=result.get("error"))

    except Exception as e:
        return ConnectionTestResult(success=False, error=str(e))
