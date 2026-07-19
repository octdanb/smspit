"""WebSocket event hub: pushes dashboard-relevant events to connected clients.

Events (see SPEC §7): message.created, message.status_changed, messages.cleared.
Payloads carry the internal (dashboard) message shape, not the Twilio shape.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event_type: str, data: dict | None = None) -> None:
        message = {"type": event_type, "data": data or {}}
        async with self._lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                await self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    from .config import config

    if config.dashboard_token and websocket.query_params.get("token") != config.dashboard_token:
        await websocket.close(code=4401)
        return
    await manager.connect(websocket)
    try:
        while True:
            # Inbound frames are ignored; the socket exists for server pushes.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
