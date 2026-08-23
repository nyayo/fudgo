"""Real-time WebSocket API.

Channels:
- ``order:{order_id}`` — customer track + courier own + restaurant-specific updates
- ``restaurant:{restaurant_id}:orders`` — restaurant incoming order stream
- ``courier:available`` — couriers watching for new available orders
- ``courier:{courier_id}:assigned`` — individual courier's accepted orders
"""
from app.realtime import (  # noqa: F401
    auth,
    connection_manager,
    heartbeat,
    router,
)
