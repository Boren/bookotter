"""
WebSocket connection manager for broadcasting sync events to connected clients.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the server's event loop so worker threads can broadcast."""
        self._loop = loop

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event: str, data: Any):
        """Send an event to all connected clients."""
        message = {"event": event, "data": data}
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    def broadcast_sync(self, event: str, data: Any) -> None:
        """Schedule async broadcast from sync code. Safe outside event loop.

        Works both on the event-loop thread (create_task) and from worker
        threads such as FastAPI background tasks or the scheduler
        (run_coroutine_threadsafe via the loop recorded by ``set_loop``).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            loop.create_task(self.broadcast(event, data))
            return

        if self._loop is not None and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.broadcast(event, data), self._loop)
            return

        logger.debug(f"No running event loop; skipping broadcast of '{event}'")

    async def send_to(self, websocket: WebSocket, event: str, data: Any):
        """Send an event to a specific client."""
        message = {"event": event, "data": data}
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self.active_connections)


# Global manager instance
manager = WebSocketManager()
