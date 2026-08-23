"""In-process WebSocket pub/sub.

No FastAPI import, no DB. One :class:`ConnectionManager` per Uvicorn process.

Channels are topic strings; each channel holds a set of connected
:class:`fastapi.WebSocket` instances. Sending broadcasts to all WS in a
channel; stale connections are dropped on send failure.

This is the v1 design — single-process only. Multi-replica support will
need Redis pub/sub (Phase 7+).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, status


def _json_default(obj: Any) -> Any:
    """Serialise common non-JSON types (datetime, UUID, Decimal)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "hex"):  # UUID
        return obj.hex
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"Cannot serialise {type(obj).__name__}")


class ConnectionManager:
    """In-process pub/sub. Channels map ``channel -> set[WebSocket]``."""

    def __init__(
        self,
        max_per_user: int = 5,
        ping_interval_s: int = 30,
        pong_timeout_s: int = 10,
    ) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._user_channels: dict[str, set[str]] = defaultdict(set)
        # Track the actual number of WebSocket connections per user (not
        # the number of channels they're subscribed to). Cap enforcement
        # uses this so two users sharing the same channel are counted
        # separately.
        self._user_connection_count: dict[str, int] = defaultdict(int)
        self._ws_to_user: dict[WebSocket, str] = {}
        self._max_per_user = max_per_user
        self._ping_interval_s = ping_interval_s
        self._pong_timeout_s = pong_timeout_s
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # connect / disconnect
    # ------------------------------------------------------------------

    async def connect(
        self, channel: str, websocket: WebSocket, user_id: str
    ) -> bool:
        """Accept + register. Returns False if the per-user cap is hit."""
        async with self._lock:
            if self._user_connection_count[user_id] >= self._max_per_user:
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Too many connections",
                )
                return False
            await websocket.accept()
            self._channels[channel].add(websocket)
            self._user_channels[user_id].add(channel)
            self._user_connection_count[user_id] += 1
            self._ws_to_user[websocket] = user_id
            return True

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        user_id = self._ws_to_user.pop(websocket, None)
        if channel in self._channels:
            self._channels[channel].discard(websocket)
            if not self._channels[channel]:
                del self._channels[channel]
        if user_id is not None:
            if user_id in self._user_channels:
                self._user_channels[user_id].discard(channel)
                if not self._user_channels[user_id]:
                    del self._user_channels[user_id]
            self._user_connection_count[user_id] -= 1
            if self._user_connection_count[user_id] <= 0:
                del self._user_connection_count[user_id]

    # ------------------------------------------------------------------
    # broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, channel: str, event: dict[str, Any]) -> None:
        """Send ``event`` (JSON-encoded) to every WS in ``channel``.

        Stale / dead connections are removed on send failure.
        """
        message = json.dumps(event, default=_json_default)
        dead: list[WebSocket] = []
        for ws in list(self._channels.get(channel, ())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)

    async def send_to_user(self, user_id: str, event: dict[str, Any]) -> None:
        """Send ``event`` to every channel the user is currently subscribed to."""
        for channel in list(self._user_channels.get(user_id, ())):
            await self.broadcast(channel, event)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total_channels": len(self._channels),
            "total_connections": sum(len(s) for s in self._channels.values()),
            "total_users": len(self._user_channels),
        }

    @property
    def ping_interval_s(self) -> int:
        return self._ping_interval_s

    @property
    def pong_timeout_s(self) -> int:
        return self._pong_timeout_s

    @property
    def max_per_user(self) -> int:
        return self._max_per_user


def make_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Helper to stamp ``type`` + ``at`` ISO-8601 timestamp on an event."""
    return {
        "type": event_type,
        "data": data,
        "at": datetime.now(UTC).isoformat(),
    }
