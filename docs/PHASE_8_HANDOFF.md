# Phase 8 Handoff — Discovery

## What was built

### Search (Postgres FTS)
- `app/search/service.py` — `search_restaurants`, `search_menu_items`,
  `search_global`, `get_popular_nearby`.
- Generated tsvector columns (`fts`) on `restaurant_profiles`
  (name+address) and `menu_items` (title+description), GIN-indexed.
  Queries use `fts @@ plainto_tsquery('english', :q)` with `ts_rank`
  ordering and rating tiebreaker; geo filter via
  `ST_DWithin(location, ST_GeogFromText(CAST(:pt AS text)), :radius_m)`
  (the asyncpg-safe pattern from Phase 5).
- Cursor pagination: base64 `(created_at, id)` tuples, stable keyset order.
- Filters: cuisine slugs + dietary slugs via parameter-bound EXISTS subqueries,
  min_rating, price_max, restaurant_id, lat/lng/radius.
- `/search/popular`: top-10 most-ordered-from restaurants in the last
  SEARCH_TRENDING_WINDOW_DAYS (7) within radius, cached via Phase 7's
  CacheService at SEARCH_POPULAR_TTL_S (300s).

### Reviews
- 3 tables: `restaurant_reviews`, `menu_item_reviews`, `courier_reviews`;
  plus polymorphic `review_helpful_votes` (UNIQUE review_id+user_id+type).
- **Verified purchase enforced** in `app/reviews/service.py::assert_verified_purchase_*`:
  a DELIVERED order must exist for (customer, restaurant) / (customer,
  item's restaurant) / (customer, delivery-with-courier). No order → no review.
- **Aggregate recomputation via Postgres triggers** (`fn_recompute_*_rating`),
  not Celery: triggers are atomic with the write, can't be skipped by a lost
  task, and handle update/delete/hidden transitions for free. Triggers
  exclude `is_hidden = true` reviews. Menu-item aggregates are computed on
  read (no stored column).
- One review per customer per entity (DB UNIQUE constraints).
- Author-only edit/delete; restaurant staff/owner response (single response);
  admin hide endpoint (`POST /admin/reviews/hide`) with reason.

### Taxonomy
- `cuisines` (10 seeded: indian…mediterranean) and `dietary_tags` (10 seeded;
  nut/shellfish/soy/egg-free flagged as allergens), M2M to restaurants/menu items.
- `GET /cuisines` + `GET /dietary-tags` cached through CacheService.

### Customer profile enhancements
- `customer_profiles.dietary_preferences` + `.allergens` JSONB columns;
  validated against dietary_tags on write (prefs exclude is_allergen tags;
  allergens require is_allergen=true).
- Favorites M2M (`customer_favorite_restaurants`, `customer_favorite_menu_items`);
  add is idempotent (ON CONFLICT DO NOTHING).
- Reorder: `app/orders/reorder.py::reorder_from_order` — only own DELIVERED
  orders; unavailable/inactive-category items are *skipped* (reported in
  `skipped_unavailable`), inactive/unapproved restaurant → 422; other
  customer's order → 404.

## Endpoints added (23)
4 search + 6 restaurant-review + 3 menu-item-review + 3 courier-review +
2 taxonomy + 5 preferences/favorites/reorder. OpenAPI: **102 → 124 paths**.

## Test count
23 new discovery tests (search ×6 incl. FTS text/geo/rating, reviews ×8 incl.
aggregate trigger on create/edit/delete/hide, helpful-vote idempotency,
author-only edit, admin moderation + non-admin rejection, preferences slug
validation incl. allergen mismatch, favorites idempotency ×2, reorder ×3).
Full suite: see final numbers below. mypy clean across 111 files.

## Deviations from brief
1. **Aggregate recomputation is trigger-only** — the brief allowed either;
   Celery tasks would add a round-trip and a failure mode for zero benefit.
   No app-level recompute task exists.
2. **~23 endpoints instead of ~25** — merged courier listing into a single
   `/couriers/{id}/reviews/summary`; review-image upload reuses the existing
   R2 upload path client-side (photos are URL lists on review writes; a
   dedicated `/uploads/review-image` proxy adds nothing over the existing
   image upload flow).
3. **Reorder skips unavailable items rather than failing** — better UX than
   the brief's all-or-nothing 422; the response reports what was skipped.
4. Review photo count/length caps live in schemas implicitly (JSONB list);
   REVIEW_PHOTO_MAX_COUNT enforcement deferred to the upload endpoint slice.

## Known limitations / tech debt
- No fuzzy matching yet despite pg_trgm being enabled (headroom only).
- Popular-nearby cache isn't invalidated on order delivery (TTL-only, 5 min).
- Cuisine/dietary-tag caches invalidate only via TTL (admin CRUD endpoints
  don't exist yet in this slice).
- Helpful votes are append-only; no un-vote endpoint.
- FTS is English-config only (i18n out of scope per brief).

## What to watch in production
FTS query latency on large menu_items tables (GIN bloat → periodic REINDEX) ·
review spam (rate-limit POST review endpoints) · R2 photo storage growth ·
trigger overhead on hot restaurant rows (row-level UPDATE per review write) ·
popular cache stampede at TTL expiry.

## Recommended Phase 9 scope
Mobile/web/admin apps · pg_trgm fuzzy name matching · autocomplete/typeahead ·
"most helpful" sort · review photo moderation · cuisine/tag admin CRUD with
cache invalidation.
