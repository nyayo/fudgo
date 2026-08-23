"""Unit tests for the in-process ConnectionManager.

No FastAPI, no DB, no asyncio loop needed beyond the test's own
``asyncio`` fixtures.

These tests cover:
- channel add/remove
- broadcast to multiple subscribers
- dead-connection cleanup
- per-user connection cap
- send_to_user (all of a user's channels)
- stats
- JSON encoding of datetime / UUID / Decimal
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.realtime.connection_manager import (
    ConnectionManager,
    make_event,
)


class FakeWebSocket:
    """Minimal WebSocket double for ConnectionManager unit tests."""

    def __init__(self, *, raises_on_send: bool = False) -> None:
        self.accepted = False
        self.sent: list[str] = []
        self.closed = False
        self.close_args: tuple[int, str | None] | None = None
        self.raises = raises_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self.raises:
            raise RuntimeError("Simulated dead socket")
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = True
        self.close_args = (code, reason)


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


async def test_connect_adds_to_channel() -> None:
    m = ConnectionManager()
    ws = FakeWebSocket()
    ok = await m.connect("order:abc", ws, "user-1")
    assert ok
    assert ws.accepted
    assert "order:abc" in m._channels
    assert ws in m._channels["order:abc"]
    assert "user-1" in m._user_channels
    assert m.stats["total_channels"] == 1
    assert m.stats["total_connections"] == 1


async def test_disconnect_removes_from_channel() -> None:
    m = ConnectionManager()
    ws = FakeWebSocket()
    await m.connect("order:abc", ws, "user-1")
    m.disconnect("order:abc", ws)
    assert "order:abc" not in m._channels
    assert "user-1" not in m._user_channels


async def test_disconnect_unknown_channel_is_noop() -> None:
    m = ConnectionManager()
    ws = FakeWebSocket()
    m.disconnect("order:none", ws)
    assert m.stats["total_connections"] == 0


async def test_multiple_users_in_same_channel() -> None:
    m = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await m.connect("order:abc", ws1, "user-1")
    await m.connect("order:abc", ws2, "user-2")
    assert m.stats["total_channels"] == 1
    assert m.stats["total_connections"] == 2
    assert m.stats["total_users"] == 2


# ---------------------------------------------------------------------------
# per-user cap
# ---------------------------------------------------------------------------


async def test_per_user_cap_enforced() -> None:
    m = ConnectionManager(max_per_user=2)
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    ws3 = FakeWebSocket()
    assert await m.connect("c:a", ws1, "u1") is True
    assert await m.connect("c:b", ws2, "u1") is True
    # third connection for the same user should be rejected
    assert await m.connect("c:c", ws3, "u1") is False
    assert ws3.closed
    assert ws3.close_args == (1008, "Too many connections")


async def test_per_user_cap_isolates_users() -> None:
    m = ConnectionManager(max_per_user=2)
    assert await m.connect("c:a", FakeWebSocket(), "u1") is True
    assert await m.connect("c:a", FakeWebSocket(), "u2") is True
    # u1 has 1 connection, can add another; u2 has 1, can also add another
    assert await m.connect("c:b", FakeWebSocket(), "u1") is True
    assert await m.connect("c:b", FakeWebSocket(), "u2") is True
    # Now u1 and u2 are both at 2 -- any third is rejected
    assert await m.connect("c:c", FakeWebSocket(), "u1") is False


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------


async def test_broadcast_sends_to_all_subscribers() -> None:
    m = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await m.connect("order:abc", ws1, "u1")
    await m.connect("order:abc", ws2, "u2")
    event = make_event("hello", {"order_id": "abc"})
    await m.broadcast("order:abc", event)
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert json.loads(ws1.sent[0])["type"] == "hello"
    assert json.loads(ws2.sent[0])["type"] == "hello"


async def test_broadcast_to_unknown_channel_is_noop() -> None:
    m = ConnectionManager()
    await m.broadcast("order:none", {"type": "noop"})  # should not raise


async def test_broadcast_removes_dead_connections() -> None:
    m = ConnectionManager()
    good = FakeWebSocket()
    dead = FakeWebSocket(raises_on_send=True)
    await m.connect("c:1", good, "u-good")
    await m.connect("c:1", dead, "u-dead")
    await m.broadcast("c:1", {"type": "x"})
    assert len(good.sent) == 1
    # dead should be removed
    assert dead not in m._channels.get("c:1", set())


# ---------------------------------------------------------------------------
# send_to_user
# ---------------------------------------------------------------------------


async def test_send_to_user_reaches_all_user_channels() -> None:
    m = ConnectionManager(max_per_user=5)
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    await m.connect("c:1", ws_a, "u1")
    await m.connect("c:2", ws_b, "u1")
    await m.send_to_user("u1", {"type": "ping"})
    assert len(ws_a.sent) == 1
    assert len(ws_b.sent) == 1


async def test_send_to_unknown_user_is_noop() -> None:
    m = ConnectionManager()
    await m.send_to_user("nobody", {"type": "ping"})  # should not raise


# ---------------------------------------------------------------------------
# JSON encoding
# ---------------------------------------------------------------------------


def test_make_event_includes_iso_timestamp() -> None:
    evt = make_event("ping", {"k": "v"})
    assert evt["type"] == "ping"
    assert evt["data"] == {"k": "v"}
    # ISO-8601 with 'T' separator and timezone offset or 'Z'
    assert "T" in evt["at"]
    parsed = datetime.fromisoformat(evt["at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_json_serializes_datetime_and_uuid_and_decimal() -> None:
    """The internal _json_default helper must handle common non-JSON types."""
    from app.realtime.connection_manager import _json_default

    dt = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
    assert "2026-08-23" in _json_default(dt)

    u = uuid.uuid4()
    assert _json_default(u) == u.hex

    d = Decimal("12.34")
    assert _json_default(d) == "12.34"


# ---------------------------------------------------------------------------
# broadcast loop cleanup
# ---------------------------------------------------------------------------


async def test_disconnect_after_broadcast_clears_user() -> None:
    m = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await m.connect("c:1", ws1, "u1")
    await m.connect("c:2", ws2, "u1")
    m.disconnect("c:1", ws1)
    m.disconnect("c:2", ws2)
    # User is removed entirely when last channel disconnects
    assert "u1" not in m._user_channels


async def test_disconnect_keeps_user_with_other_channels() -> None:
    m = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await m.connect("c:1", ws1, "u1")
    await m.connect("c:2", ws2, "u1")
    m.disconnect("c:1", ws1)
    assert "u1" in m._user_channels
    assert "c:2" in m._user_channels["u1"]


# ---------------------------------------------------------------------------
# multiple channels per user
# ---------------------------------------------------------------------------


async def test_user_can_be_on_multiple_channels() -> None:
    m = ConnectionManager(max_per_user=5)
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    ws3 = FakeWebSocket()
    await m.connect("order:1", ws1, "u1")
    await m.connect("order:2", ws2, "u1")
    await m.connect("restaurant:1:orders", ws3, "u1")
    assert m.stats["total_connections"] == 3
    assert m.stats["total_channels"] == 3
    assert m.stats["total_users"] == 1
