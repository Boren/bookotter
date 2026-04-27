from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.utils.filesystem import list_local_directory

router = APIRouter()

# These endpoints inherit the app's unauthenticated API posture; use reverse-proxy auth for production exposure.


class BrowseEntry(BaseModel):
    name: str
    type: str
    is_symlink: bool
    size: int | None


class BrowseResponse(BaseModel):
    current_path: str
    parent_path: str | None
    exists: bool
    is_dir: bool
    is_writable: bool | None
    entries: list[BrowseEntry]
    truncated: bool


@router.get("/local", response_model=BrowseResponse)
async def browse_local_directory(
    path: str = Query(...),
    show_hidden: bool = Query(False),
):
    try:
        return list_local_directory(path, show_hidden=show_hidden)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=f"Not a directory: {e}") from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {e}") from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Path not found: {e}") from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
