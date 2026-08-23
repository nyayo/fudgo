"""WebSocket ping/pong lifecycle helpers."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, status

from app.realtime.connection_manager import ConnectionManager


async def send_ping(websocket: WebSocket) -> None:
    await websocket.send_text(
        json.dumps(
            {"type": "ping", "at": datetime.now(UTC).isoformat()}
        )
    )


async def heartbeat_loop(
    websocket: WebSocket,
    manager: ConnectionManager,
    channel: str,
) -> None:
    """Send a ping every ``manager.ping_interval_s``.

    Closes the connection if a pong is not received within
    ``manager.pong_timeout_s``. This coroutine returns when the connection
    ends; the main receive loop should ``cancel()`` it on disconnect.
    """
    try:
        while True:
            await asyncio.sleep(manager.ping_interval_s)
            try:
                await send_ping(websocket)
                # Wait for the client to reply; receive_text() returns when
                # the client sends any frame, including a pong payload.
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=manager.pong_timeout_s,
                )
            except asyncio.TimeoutError:
                manager.disconnect(channel, websocket)
                with suppress(Exception):
                    await websocket.close(
                        code=status.WS_1011_INTERNAL_ERROR,
                        reason="pong timeout",
                    )
                return
    except asyncio.CancelledError:
        manager.disconnect(channel, websocket)
        with suppress(Exception):
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
        raise
    except Exception:
        manager.disconnect(channel, websocket)
        with suppress(Exception):
            await websocket.close(
                code=status.WS_1011_INTERNAL_ERROR,
                reason="heartbeat error",
            )


def is_pong(message: dict[str, Any]) -> bool:
    """Client pong message format: ``{"type": "pong"}``."""
    return isinstance(message, dict) and message.get("type") == "pong"
