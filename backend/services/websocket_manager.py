"""
WebSocket connection manager for broadcasting sync events to connected clients.
"""

from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

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
