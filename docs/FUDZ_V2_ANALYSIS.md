# Fudz API v2 — Analysis & Decision Log

## What v1 is

v1 is a multi-tenant food-delivery backend built on Django 5.2 + DRF. Six
Django apps:

| App        | Purpose                              | Key models                                                                                                                                                                 |
| ---------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| users      | Multi-provider auth, 4 role profiles | User (AbstractUser with email/phone/google_id/auth_provider), EmailVerification, PhoneVerification, CustomerProfile, CourierProfile, RestaurantProfile, RestaurantStaffProfile, Address, NotificationPreference |
| restaurants | Menus, categories, items, promotions | Promotion, MenuCategory, MenuItem, MenuItemImage, MenuCategoryImage                                                                                                        |
| orders     | Cart + order lifecycle               | Cart, CartItem, Order, OrderItem (with applied_promotion, discount_amount), Notification                                                                                   |
| delivery   | Courier assignment + live tracking   | DeliveryRequest, DeliveryTracking, CourierEarnings                                                                                                                         |
| reviews    | Restaurant ratings                   | RestaurantReview (1 review per customer/restaurant pair)                                                                                                                   |
| wishlist   | Per-customer saved items             | Wishlist, WishlistItem                                                                                                                                                     |

~8,800 LOC. Real-time via Django Channels (Redis), async via Celery, media on
Cloudflare R2, push via Firebase Admin SDK, geo via PostGIS.

## Infrastructure mapping v1 → v2

| Infra        | v1                                  | v2 (this repo)                                                       |
| ------------ | ----------------------------------- | -------------------------------------------------------------------- |
| Web          | Django 5.2 + DRF                    | **FastAPI** (async)                                                  |
| ORM          | Django ORM                          | **SQLModel + asyncpg**                                               |
| Migrations   | Django migrations                   | **Alembic** (async env)                                              |
| Real-time    | Django Channels (Redis layer)       | FastAPI WebSocket + Redis pub/sub (later phases)                     |
| Async jobs   | Celery 5 + Redis broker             | **Celery (unchanged)**                                               |
| DB           | Postgres + PostGIS                  | **PostGIS kept** (geography points, distance ordering)               |
| Cache        | Redis                               | Redis (kept)                                                         |
| Storage      | Cloudflare R2 (boto3)               | R2 (kept; later phase wires it up)                                   |
| Push         | Firebase Admin SDK                  | firebase_admin (kept; later phase)                                   |
| Auth         | DRF-simplejwt + Google OAuth + OTP  | **Custom JWT (python-jose)** + Google OAuth + email/phone OTP        |
| Docs         | drf-spectacular                     | FastAPI native OpenAPI at /docs, /redoc                              |
| Metrics      | django-prometheus                   | **prometheus-fastapi-instrumentator**                                |
| Throttling   | DRF throttle classes                | **slowapi** (later phase)                                            |
| Settings     | python-decouple                     | **pydantic-settings**                                                |
| Logging      | stdlib logging                      | **structlog** (JSON output)                                          |

## Response envelope (frontend contract — must be preserved in every phase)

```json
// Success
{ "success": true, "data": { ... } }

// Error
{ "success": false, "error": { "code": 400, "message": "...", "details": { ... } } }
```

## v1 throttle rates (carried into later phases)

- `otp: 5/minute`
- `password_reset: 3/hour`
- `google_auth: 10/minute`
- `user: 1000/hour`
- `anon: 100/hour`

## User role type

`customer | courier | restaurant | restaurant_staff`

## Order status machine

`placed → accepted → ready → picked_up → delivered`
`→ cancelled` possible from any active step.

## Delivery status machine

`pending → assigned → accepted → picked_up → delivered`
`→ declined | cancelled`

## Auth providers

Enum: `email | phone | google | github | linkedin`. Phase 0 / Phase 1 only
implement `email | phone | google`; `github/linkedin` values are mirrored for
future-proofing.

## Locked-in decisions (do not re-debate)

| Decision            | Choice                                                    | Why                                        |
| ------------------- | --------------------------------------------------------- | ------------------------------------------ |
| Repo                | New `Fudz_api_v2` on github: nyayo                        | Clean history, no v1 migration cruft       |
| Geo                 | PostGIS stays                                             | Mirror v1's geography=True PointFields     |
| Auth                | Custom JWT (python-jose), no fastapi-users                | Full control over the auth flow            |
| Sync vs async       | Async FastAPI                                             | WebSockets + heavy I/O                     |
| Cutover (later)     | Dual-run, feature-flagged, slice by slice                 | Phase 0 only sets up infra for it          |
| HTTP path           | `/api/v2/*` (and `/ws/v2/*` for WS later)                 | Match the v1 versioning pattern            |
| Frontend compat     | Same JSON envelope, same field names                      | Preserve frontend                          |

## Phases

- **Phase 0 — Foundation** (this brief): boot, DB (PostGIS), Alembic, health,
  docs, metrics, dev environment, CI. No auth, no feature models.
- **Phase 1 — Auth + Users**: custom JWT (python-jose), register/login/logout,
  Google OAuth, email/phone OTP, profiles, throttling via slowapi, storage via
  R2, push device registration — all envelope-compliant and feature-flagged for
  cutover.
- Subsequent phases pick off: restaurants/menus, cart/orders, delivery,
  reviews, wishlist, websockets (Redis pub/sub), celery tasks, etc.

## Env vars (Phase 0)

See `README.md` endpoint/env table and `.env.example` in the repo root.
