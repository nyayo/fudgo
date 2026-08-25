# Pre-flight — Phase 6.5 (Before Phase 7)

1. **Branch/worktree**: `feature/phase-7-scale` off `main` @ `ee2f2eb` (Phase 6 + env docs).
2. **Suite**: 287 passed / 1 skipped (documented Phase 3 promo edge case) before Phase 7 work.
3. **mypy**: clean, 101 source files.
4. **OpenAPI**: 102 paths, no drift.
5. **ConnectionManager audit**: interface is `connect(channel, ws, user_id) -> bool`,
   `disconnect(channel, ws)`, `broadcast(channel, event)`, `send_to_user(user_id, event)`,
   `stats`, `ping_interval_s`. Note: actual signature differs slightly from the brief's
   sketch (`disconnect` derives user_id internally; `connect` returns bool for the cap).
   The Phase 7 implementation preserves the REAL Phase 4 interface, not the sketch.
6. **redis>=5.0 already in deps** (celery[redis]); only fakeredis added as dev dep.
7. **REDIS_URL** already exists in config (REDIS_HOST/PORT/DB + REDIS_URL_RESOLVED);
   reused rather than duplicated.
8. **No migration needed** — no schema changes required; existing indexes on
   orders.status/courier_id and restaurant_profiles GIST cover the hot queries.
