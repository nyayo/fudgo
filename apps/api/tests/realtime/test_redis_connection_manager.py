"""RedisConnectionManager tests — fakeredis-backed, including the
headline multi-replica broadcast test."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

fakeredis = pytest.importorskip("fakeredis")


class _FakeWS:
    """Minimal WebSocket double: records send_text calls."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.sent: list[str] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True

    async def send_text(self, data: str) -> None:
        if getattr(self, "dead", False):
            raise RuntimeError("connection closed")
        self.sent.append(data)


@pytest.fixture
def fake_redis() -> Any:
    from fakeredis import aioredis as fr

    return fr.FakeRedis(decode_responses=True)


async def _wait_for(predicate: Any, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


# ---------------------------------------------------------------------------
# The headline test
# ---------------------------------------------------------------------------


async def test_broadcast_across_two_managers(fake_redis: Any) -> None:
    """Broadcast on replica A must reach a WS connected to replica B."""
    from app.realtime.connection_manager import RedisConnectionManager

    cm_a = RedisConnectionManager(fake_redis)
    cm_b = RedisConnectionManager(fake_redis)
    await cm_a.start()
    await cm_b.start()
    try:
        ws_a = _FakeWS("a")
        ws_b = _FakeWS("b")
        assert await cm_a.connect("order:x", ws_a, "user-1") is True
        assert await cm_b.connect("order:x", ws_b, "user-2") is True

        await cm_b.broadcast("order:x", {"type": "order.placed"})

        ok_a = await _wait_for(lambda: len(ws_a.sent) > 0)
        ok_b = await _wait_for(lambda: len(ws_b.sent) > 0)
        assert ok_a and ok_b, (
            f"cross-replica fanout failed: a={ws_a.sent} b={ws_b.sent}"
        )
        event_a = json.loads(ws_a.sent[0])
        event_b = json.loads(ws_b.sent[0])
        assert event_a == event_b == {"type": "order.placed"}
    finally:
        await cm_a.stop()
        await cm_b.stop()


async def test_broadcast_reaches_local_socket(fake_redis: Any) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis)
    await cm.start()
    try:
        ws = _FakeWS("local")
        await cm.connect("restaurant:y", ws, "u1")
        await cm.broadcast("restaurant:y", {"type": "ping"})
        assert await _wait_for(lambda: len(ws.sent) > 0)
        assert json.loads(ws.sent[0]) == {"type": "ping"}
    finally:
        await cm.stop()


async def test_pubsub_subscribe_unsubscribe_no_leaked_tasks(
    fake_redis: Any,
) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis)
    assert cm._pubsub_task is None
    await cm.start()
    task = cm._pubsub_task
    assert task is not None and not task.done()
    assert cm.stats["redis_pubsub"] == "active"
    await cm.stop()
    assert cm._pubsub_task is None
    assert cm.stats["redis_pubsub"] == "inactive"
    # Task finished without exception.
    assert task.cancelled() or task.exception() is None


async def test_invalid_payload_does_not_crash_listener(fake_redis: Any) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis)
    await cm.start()
    try:
        ws = _FakeWS("a")
        await cm.connect("ch:bad", ws, "u1")
        # Publish garbage directly on the redis channel.
        await fake_redis.publish("ws:broadcast:ch:bad", "{not json")
        await fake_redis.publish("ws:broadcast:ch:bad", json.dumps({"ok": 1}))
        ok = await _wait_for(lambda: len(ws.sent) > 0)
        assert ok  # valid message after garbage still delivered
    finally:
        await cm.stop()


async def test_dead_socket_removed_on_fanout(fake_redis: Any) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis)
    await cm.start()
    try:
        ws = _FakeWS("dead")
        ws.dead = True  # send_text will raise
        await cm.connect("ch:d", ws, "u1")
        assert cm.stats["total_connections"] == 1
        await cm.broadcast("ch:d", {"x": 1})
        assert await _wait_for(lambda: cm.stats["total_connections"] == 0)
    finally:
        await cm.stop()


async def test_send_to_user_publishes_to_user_channels(fake_redis: Any) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis)
    await cm.start()
    try:
        ws = _FakeWS("a")
        await cm.connect("order:z", ws, "user-9")
        await cm.send_to_user("user-9", {"type": "nudge"})
        assert await _wait_for(lambda: len(ws.sent) > 0)
    finally:
        await cm.stop()


async def test_per_user_cap_enforced(fake_redis: Any) -> None:
    from app.realtime.connection_manager import RedisConnectionManager

    cm = RedisConnectionManager(fake_redis, max_per_user=1)
    w1, w2 = _FakeWS("1"), _FakeWS("2")
    assert await cm.connect("c1", w1, "u") is True
    assert await cm.connect("c2", w2, "u") is False
    assert w2.closed


# ---------------------------------------------------------------------------
# InMemory compat
# ---------------------------------------------------------------------------


async def test_in_memory_broadcast_local_only() -> None:
    """InMemory mode: broadcast reaches only local channels (Phase 4)."""
    from app.realtime.connection_manager import InMemoryConnectionManager

    cm = InMemoryConnectionManager()
    ws = _FakeWS("a")
    await cm.connect("c", ws, "u")
    await cm.broadcast("c", {"t": 1})
    assert ws.sent == [json.dumps({"t": 1})]
