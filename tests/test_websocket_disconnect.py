"""WebSocket disconnect resilience tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.websocket_manager import WebSocketManager


class TestWebSocketDisconnect:
    def test_broadcast_handles_disconnected_client(self):
        """Broadcast tolerates one disconnected client and still serves healthy ones."""
        manager = WebSocketManager()
        good_client = MagicMock()
        good_client.send_json = AsyncMock()
        bad_client = MagicMock()
        bad_client.send_json = AsyncMock(side_effect=Exception("connection closed"))
        manager.active_connections = [good_client, bad_client]

        asyncio.run(manager.broadcast("test_event", {"data": "value"}))

        good_client.send_json.assert_awaited_once_with({"event": "test_event", "data": {"data": "value"}})
        bad_client.send_json.assert_awaited_once_with({"event": "test_event", "data": {"data": "value"}})

    def test_disconnect_mid_broadcast_removes_client(self):
        """A client that errors during broadcast is removed from active connections."""
        manager = WebSocketManager()
        good_client = MagicMock()
        good_client.send_json = AsyncMock()
        bad_client = MagicMock()
        bad_client.send_json = AsyncMock(side_effect=Exception("RST"))
        manager.active_connections = [good_client, bad_client]

        asyncio.run(manager.broadcast("test_event", {"data": "value"}))

        assert good_client in manager.active_connections
        assert bad_client not in manager.active_connections
        assert manager.connection_count == 1

    def test_broadcast_sync_with_disconnected_client_without_loop(self):
        """Sync wrapper swallows missing-loop case even if clients exist."""
        manager = WebSocketManager()
        bad_client = MagicMock()
        bad_client.send_json = AsyncMock(side_effect=Exception("closed"))
        manager.active_connections = [bad_client]

        with patch("backend.services.websocket_manager.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            assert manager.broadcast_sync("test_event", {"data": "value"}) is None
