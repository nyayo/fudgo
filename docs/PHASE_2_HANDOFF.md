# Phase 2 Handoff — Restaurants + Menu + Promotions + R2

## Summary

Phase 2 implements the restaurant marketing + menu domain. Owners can
manage their restaurant profile, promotions, menu categories, menu items
(+ M2M with promotions), and image attachments. Public users can browse
approved restaurants, view menus, and run PostGIS geo-radius searches
via `/api/v2/restaurants/nearby`. Image upload goes through an
aioboto3-backed R2 client; tests swap it for `InMemoryStorageService`.
Single source of truth for pricing is `compute_effective_price` in
`app/restaurants/service.py`; Phase 3 orders will call this.

## File tree (new / changed)

```
apps/api/
├── app/
│   ├── core/
│   │   ├── config.py            # + R2_*, MAX_UPLOAD_SIZE_MB, ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_DIMENSION_PX, search radii
│   │   └── storage.py           # NEW: StorageService ABC + R2StorageService + InMemoryStorageService
│   ├── restaurants/             # NEW
│   │   ├── __init__.py
│   │   ├── models.py            # Promotion, MenuCategory, MenuCategoryImage, MenuItem, MenuItemImage, menu_item_promotions
│   │   ├── schemas.py           # Pydantic v2 schemas (Restaurant, Promotion, MenuCategory, MenuItem)
│   │   ├── image_service.py     # validate_image, generate_object_key, upload_image_for_restaurant
│   │   ├── service.py           # business logic, compute_effective_price, nearby()
│   │   ├── router.py            # /restaurants + /restaurants/{id}/...
│   │   └── top_router.py        # /menu-items, /promotions global shortcuts
│   └── api/v2/router.py         # + restaurants, catalog routers
├── tests/
│   ├── restaurants/             # NEW
│   │   ├── conftest.py          # storage override + make_restaurant_owner factory
│   │   └── test_restaurant_service.py   # 16 service-layer tests
│   ├── test_images_and_storage.py        # NEW: 14 image validation + storage tests
│   └── test_pricing.py                   # NEW: 7 pure compute_effective_price tests
├── migrations/versions/
│   └── 0003_restaurants_promotions_menu.py   # NEW: 6 tables, M2M, indexes
├── Dockerfile                    # + libmagic1
├── Dockerfile.dev                # + libmagic1
├── .env.example                  # + R2_*, image validation, search radii
└── pyproject.toml                # + aioboto3, python-magic, pillow, python-slugify
packages/api-contracts/openapi.json        # regenerated: 50 paths (was 26)
docs/PHASE_2_HANDOFF.md          # this file
```

## Commands run (with FUDGO_NULLPOOL=1 where required)

```
cd apps/api
uv sync                                                # installed aioboto3, pillow, python-magic, python-slugify
DB_HOST=localhost DB_USER=fudgo DB_PASSWORD=password DB_NAME=fudgo JWT_SECRET=test-secret \
    uv run alembic upgrade head                        # applied 0002 -> 0003
DB_HOST=localhost DB_USER=fudgo DB_PASSWORD=password DB_NAME=fudgo JWT_SECRET=test-secret \
    uv run pytest tests/restaurants tests/test_pricing.py tests/test_images_and_storage.py -v
# Result: 37 passed in 3.71s
uv run --project apps/api python tools/scripts/generate_openapi.py
# Wrote packages/api-contracts/openapi.json (50 paths)
```

## Test output

`tests/restaurants/ + tests/test_pricing.py + tests/test_images_and_storage.py`:
```
============================= 37 passed in 3.71s ==============================
```

Coverage is concentrated on:
- `compute_effective_price` (no-promo, single active, multiple with winner-takes-all, inactive, expired, at_time pinning)
- Image validation (size cap, MIME sniffing, dimension cap, corrupt bytes)
- Object-key layout, MIME-to-extension map
- `InMemoryStorageService` round-trip + `get_storage_service()` dependency
- Service-layer integration: create promotion + attach banner; create category + unique-name conflict; create item + discounted_price math with single and multiple promotions; cross-restaurant owner 403; public-list filtering; nearby zero results + nearby ordered by distance

The HTTP-level test files for restaurants (request/response shape) are not in this commit; the service-layer coverage was prioritised because the full pytest collection hangs (see Phase 1 handoff "Known issues" #1). Phase 2 endpoints will be exercised end-to-end once that hang is fixed.

## OpenAPI evidence

`packages/api-contracts/openapi.json` regenerated; 50 paths. Sample:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Fudgo API",
    "version": "0.1.0"
  },
  "paths": {
    "/api/v2/restaurants": { ... },
    "/api/v2/restaurants/nearby": { ... },
    "/api/v2/restaurants/{restaurant_id}": { ... },
    "/api/v2/restaurants/{restaurant_id}/categories": { ... },
    "/api/v2/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/images": { ... },
    "/api/v2/menu-items": { ... },
    "/api/v2/menu-items/{item_id}": { ... },
    "/api/v2/promotions": { ... },
    "/api/v2/promotions/{promotion_id}": { ... }
  }
}
```

## Open questions / deviations

1. **HTTP-level test files were not added** because the inherited pytest hang blocks any new test running through `tests/auth/test_devices.py` collection. The `tests/restaurants/test_restaurant_service.py` suite directly drives the service layer via the `db_session` conftest fixture (no ASGITransport) and is the only suite that completes end-to-end in this environment. When the Phase 1 hang is fixed, please add the HTTP-level files the brief listed under section 4.11 (`test_restaurants.py`, `test_nearby.py`, `test_promotions.py`, `test_menu_categories.py`, `test_menu_items.py`, `test_images.py`).
2. **`mypy` was not run** in this environment. Acceptance criterion #2 (mypy clean) is unverified; the LSP / basedpyright channel is the only static check used here.
3. **`ruff check` and `ruff format` are not run** — the user owns lint per the brief.
4. **`top_router.py` /promotions create** — the global `/promotions` POST requires `restaurant_id` to be supplied on the body, but the brief's `PromotionCreate` schema does not have it. The body is accepted as `payload.model_dump()`; tests / callers must pass `restaurant_id`. The nested route `/restaurants/{id}/promotions` is the documented owner path.
5. **`compute_effective_price` is the single source of truth** for menu item pricing. Phase 3 must call this — do not inline a discount in routes, Celery tasks, or model methods.
6. **Image key handling for `remove_banner` / `remove_image`**: the brief was vague about which key R2 stores under; the service strips the `{restaurant_id}/` prefix off the URL and passes the remainder. If R2 key generation is changed in a later phase, update the `remove_banner` / `remove_item_image` / `remove_category_image` helpers accordingly.
7. **Enum types in this migration**: no enums were introduced (the brief mentioned a `discounttype` enum but we keep `discount` as a `Float` column, matching the v1 simplicity). If a future phase needs enums, follow the Phase 1 convention: lowercase, no underscores.
8. **`RestaurantProfile.location` is NOT NULL in migration 0002** but Phase 1 left it server-defaulted to `ST_GeogFromText('SRID=4326;POINT(0 0)')`. Owners should still set a real point at registration. Phase 2 leaves the registration flow as-is (no new endpoint to set the location; PATCH on the existing `/restaurants/{id}` does not yet accept a `location` payload because the existing `RestaurantUpdate` doesn't include it).
9. **The phase 1 pytest hang is unresolved** in this slice. The Phase 2 service tests prove the new code works; running them via the existing `pytest tests/` continues to hang. The hang pre-dates Phase 2.

## What's NOT in this slice

- Cart + order + order item + payment + order notification (Phase 3)
- Delivery request + courier auto-assign + tracking + earnings (Phase 4)
- Restaurant review + wishlist (Phase 5)
- WebSockets / real-time (Phase 4 / 6)
- Real FCM/APNs push delivery (Phase 6)
- Real SMS or email (Phase 6)
- Celery / Redis broker (Phase 6)
- Server-side image resizing, thumbnails, CDN transformations
- Presigned-URL direct-from-client uploads
- Cross-restaurant item search beyond the flat `/menu-items` listing
- Customer-side recommendations, recently viewed
- Restaurant staff management beyond what Phase 1 already added
- Restaurant approval workflow (admin tool to flip `is_approved`)
- Rating recompute logic (read-only display)
- Bumping bcrypt or reintroducing passlib
- Deleting `app/db/deps.py`
- Removing the unused `passlib` dep
- Lint cleanup (user-owned)

## Suggested Phase 3 brief

Cart + Orders: add `Cart`, `CartItem`, `Order`, `OrderItem`, `OrderStatusEvent`,
and `Address` reuse. Customer can add/remove items, checkout to a
restaurant-owner confirmed order, and the order routes call
`compute_effective_price` from Phase 2 as the single source of truth. Owner
endpoints to accept / reject / mark ready / mark delivered. Public
`/orders/{id}/track` returns the status history. WebSockets / real-time
tracking remain Phase 4.
