"""Redis-backed WebSocket pub/sub + in-process implementation.

Public interface unchanged from Phase 4:

    connect(channel, ws, user_id) -> bool
    disconnect(channel, ws)
    broadcast(channel, event)
    send_to_user(user_id, event)
    stats -> dict
    ping_interval_s -> int

``ConnectionManager`` remains an alias of :class:`InMemoryConnectionManager`
for backwards compatibility with Phase 4 call sites and tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from contextlib import suppress
from typing import Any

from fastapi import WebSocket, status

logger = logging.getLogger(__name__)

BROADCAST_PREFIX = "ws:broadcast:"


def _json_default(obj: Any) -> Any:
    """Serialise common non-JSON types (datetime, UUID, Decimal)."""
    from datetime import datetime as _dt

    if isinstance(obj, _dt):
        return obj.isoformat()
    if hasattr(obj, "hex"):  # UUID
        return obj.hex
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"Cannot serialise {type(obj).__name__}")


class InMemoryConnectionManager:
    """Phase 4 in-process pub/sub. Tests + single-replica dev mode."""

    def __init__(
        self,
        max_per_user: int = 5,
        ping_interval_s: int = 30,
        pong_timeout_s: int = 10,
    ) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._user_channels: dict[str, set[str]] = defaultdict(set)
        self._user_connection_count: dict[str, int] = defaultdict(int)
        self._ws_to_user: dict[WebSocket, str] = {}
        self._max_per_user = max_per_user
        self._ping_interval_s = ping_interval_s
        self._pong_timeout_s = pong_timeout_s
        self._lock = asyncio.Lock()

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

    async def broadcast(self, channel: str, event: dict[str, Any]) -> None:
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
        for channel in list(self._user_channels.get(user_id, ())):
            await self.broadcast(channel, event)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_channels": len(self._channels),
            "total_connections": sum(len(s) for s in self._channels.values()),
            "total_users": len(self._user_channels),
        }

    @property
    def ping_interval_s(self) -> int:
        return self._ping_interval_s


# Backwards-compat alias (Phase 4 name).
ConnectionManager = InMemoryConnectionManager


class RedisConnectionManager(InMemoryConnectionManager):
    """Multi-replica WebSocket pub/sub via Redis pub/sub.

    Local WebSocket bookkeeping is inherited from the in-process manager.
    ``broadcast()`` PUBLISHes to ``ws:broadcast:{channel}``; every process
    (including this one) receives it via a single pattern subscription
    started in app.main's lifespan and fans out to local WebSockets.
    """

    def __init__(
        self,
        redis_client: Any,
        max_per_user: int = 5,
        ping_interval_s: int = 30,
        pong_timeout_s: int = 10,
    ) -> None:
        super().__init__(
            max_per_user=max_per_user,
            ping_interval_s=ping_interval_s,
            pong_timeout_s=pong_timeout_s,
        )
        self._redis = redis_client
        self._pubsub_task: asyncio.Task[Any] | None = None
        self._pubsub: Any = None

    async def start(self) -> None:
        """Subscribe to the broadcast pattern. Call once in lifespan."""
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{BROADCAST_PREFIX}*")
        self._pubsub_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._pubsub_task
            self._pubsub_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.punsubscribe(f"{BROADCAST_PREFIX}*")
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None

    async def _safe_send(self, channel: str, ws: WebSocket, message: str) -> None:
        try:
            await ws.send_text(message)
        except Exception:
            self.disconnect(channel, ws)

    async def _fanout_local(self, logical_channel: str, message: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._channels.get(logical_channel, ())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(logical_channel, ws)

    async def _listen_loop(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                async for message in self._pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    raw_channel = (
                        message["channel"]
                        if isinstance(message["channel"], str)
                        else message["channel"].decode()
                    )
                    logical = raw_channel.removeprefix(BROADCAST_PREFIX)
                    raw_data = message["data"]
                    data = raw_data if isinstance(raw_data, str) else raw_data.decode()
                    try:
                        json.loads(data)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.error(
                            f"Invalid broadcast payload on {raw_channel}: {e}"
                        )
                        continue
                    await self._fanout_local(logical, data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"pubsub listen error, retrying in 1s: {e}")
                await asyncio.sleep(1)

    async def broadcast(self, channel: str, event: dict[str, Any]) -> None:
        """PUBLISH to Redis; all replicas (incl. this one) fan out locally."""
        await self._redis.publish(
            f"{BROADCAST_PREFIX}{channel}",
            json.dumps(event, default=_json_default),
        )

    async def send_to_user(self, user_id: str, event: dict[str, Any]) -> None:
        for channel in list(self._user_channels.get(user_id, ())):
            await self.broadcast(channel, event)

    @property
    def stats(self) -> dict[str, Any]:
        base: dict[str, Any] = super().stats
        base["redis_pubsub"] = (
            "active"
            if self._pubsub_task is not None and not self._pubsub_task.done()
            else "inactive"
        )
        return base


def make_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Helper to stamp ``type`` + ``at`` ISO-8601 timestamp on an event."""
    from datetime import UTC, datetime

    return {
        "type": event_type,
        "data": data,
        "at": datetime.now(UTC).isoformat(),
    }
