"""Real-time WebSocket API documentation."""

# Real-time API (Phase 4)

## Channels

The server is **in-process pub/sub only** (single Uvicorn process). For
multi-replica support, Redis pub/sub is required (Phase 7+).

Channel naming convention (clients don't see channel names; they connect
to a specific WS URL and receive events on that channel):

- `order:{order_id}` — customer track + courier own + restaurant-specific order updates
- `restaurant:{restaurant_id}:orders` — restaurant's incoming order stream
- `courier:available` — couriers watching for new available orders
- `courier:{courier_id}:assigned` — individual courier's accepted orders

## WebSocket endpoints

All endpoints accept the JWT access token as a `?token=...` query param.
Missing/invalid/expired token returns `close(1008)`.

| Method | Path | Auth | Receives |
| --- | --- | --- | --- |
| WS | `/api/v2/ws/orders/{order_id}/track` | order's customer | `hello`, `order.status_changed`, `order.courier_assigned`, `order.courier_location`, `order.courier_eta` |
| WS | `/api/v2/ws/restaurants/{restaurant_id}/orders` | staff of `restaurant_id` | `hello`, `order.placed`, `order.confirmed`, `order.preparing`, `order.ready`, `order.cancelled` |
| WS | `/api/v2/ws/courier/orders/available` | courier | `hello`, `courier.available_new`, `courier.available_taken` |
| WS | `/api/v2/ws/courier/orders/mine` | courier | `hello`, `order.status_changed`, `order.courier_location`, `order.courier_eta` |

## Event payload shape

All events use:

```json
{
  "type": "<event_type>",
  "data": { ... },
  "at": "<ISO-8601 timestamp>"
}
```

## Event types

- `hello` — sent immediately on connect: `{"order_id": "...", "restaurant_id": "...", "courier_id": "..."}`
- `order.placed` — `{"order_id", "restaurant_id", "customer_name", "total", "at"}`
- `order.confirmed` / `order.preparing` / `order.ready` — `{"order_id", "at"}`
- `order.status_changed` — `{"order_id", "from_status", "to_status", "at"}`
- `order.cancelled` — `{"order_id", "by_role", "reason", "at"}`
- `order.courier_assigned` — `{"order_id", "courier_id", "at"}`
- `order.courier_location` — `{"order_id", "courier_id", "lat", "lng", "heading", "speed", "recorded_at"}`
- `order.courier_eta` — `{"order_id", "pickup_eta_minutes", "delivery_eta_minutes", "at"}`
- `courier.available_new` — `{"order_id", "restaurant_id", "restaurant_name", "distance_km", "pickup_lat", "pickup_lng", "at"}`
- `courier.available_taken` — `{"order_id", "at"}`
- `ping` — server-initiated keepalive (client must respond with `{"type": "pong"}`)

## Heartbeat

- Server sends a `ping` every `WS_PING_INTERVAL_S` (default 30s).
- Client must reply with `{"type": "pong"}` (any payload works).
- If no pong within `WS_PONG_TIMEOUT_S` (default 10s), connection is closed
  with `1011 Internal Error`.

## Per-user connection cap

Default `WS_MAX_CONNECTIONS_PER_USER = 5`. Hit the cap and the next
connect returns `close(1008 Policy Violation, "Too many connections")`.

## Implementation notes

- All broadcasts are **fire-and-forget** via `asyncio.create_task`. The
  HTTP handler returns immediately after queuing the broadcast.
- In-process only — see the brief's "Known limitations / tech debt".
