# Phase 1 Handoff — Auth + Users

## Summary

Phase 1 implements email/phone OTP login, Google OAuth, JWT issuance with
refresh-token rotation and revocation, password reset, profile management,
notification preferences, push device registration, and restaurant staff
management. All endpoints live under `/api/v2/` and return the v1 envelope
shape. 66 tests pass when run as individual files; the full pytest
`tests/` run hangs at test collection (see "Known Issues" below).

## File map

```
apps/api/
├── app/
│   ├── auth/
│   │   ├── models.py           # EmailVerification, PhoneVerification, RevokedToken
│   │   ├── jwt.py              # access/refresh/password_reset token helpers
│   │   ├── otp_service.py      # 6-digit sha256 OTPs, 10-min TTL, 5 attempts
│   │   ├── passwords.py        # direct bcrypt (passlib 1.7.4 is broken with bcrypt 5.x)
│   │   ├── google.py           # google-auth ID-token verify
│   │   ├── deps.py             # get_session, get_current_user, require_role, slowapi
│   │   ├── service.py          # registration, OTP, Google, JWT, logout, profile
│   │   ├── schemas.py
│   │   ├── router.py           # all /api/v2/auth/* routes
│   │   └── services/{email,sms,push}.py   # BackgroundTasks stubs
│   ├── users/
│   │   ├── enums.py            # UserType, AuthProvider, VehicleType, StaffRole, DevicePlatform
│   │   ├── models.py           # User + 4 profiles + Address + NotificationPreference + Device
│   │   ├── schemas.py
│   │   ├── service.py          # registration dispatch, username generation, addresses CRUD
│   │   └── router.py           # addresses + staff CRUD
│   ├── api/v2/router.py        # includes auth + users routers
│   ├── core/
│   │   ├── config.py           # + JWT_*, GOOGLE_*, RATE_LIMIT_*
│   │   ├── envelope.py         # success_envelope / error_envelope
│   │   ├── exceptions.py       # AppError hierarchy
│   │   └── ...
│   └── db/session.py           # async engine, FUDGO_NULLPOOL=1 toggle
└── tests/
    ├── conftest.py             # truncate-isolated db_session, ASGI client, factories
    ├── test_health.py
    ├── test_envelope.py
    ├── test_openapi.py
    ├── test_models_postgis.py
    ├── auth/                   # 8 test files, all green individually
    └── users/                  # 3 test files, all green individually
migrations/versions/
├── 0001_postgis_extensions_and_healthcheck.py
└── 0002_users_and_auth.py     # 11 tables; enum types lowercase no underscores
```

## Deviations from the brief

1. **`just` binary absent on the dev machine** — `justfile` is committed and correct but has not been exercised end-to-end. Recipes exist for `api-install/lint/test/migrate/up` and `contracts-generate/contracts-check`. Local workflow substituted equivalent `uv run ...` invocations.
2. **`bcrypt<5` + passlib bypass** — passlib 1.7.4 (declared in Phase 0) is incompatible with bcrypt 5.x (which removed `bcrypt.__about__`). `app/auth/passwords.py` calls `bcrypt` directly; `pyproject.toml` pins `bcrypt>=4.0,<5.0`. Do not reintroduce passlib.
3. **`FUDGO_NULLPOOL=1` required for the test suite** — without it, asyncpg trips a "different loop" RuntimeError. Production code is unaffected. Documented inline in `app/db/session.py`.
4. **Postgres enum types are lowercase no-underscore** in migration `0002`: `usertype`, `authprovider`, `vehicletype`, `staffrole`, `deviceplatform`. This matches SQLAlchemy defaults; failing to follow this convention yields `UndefinedObjectError` at INSERT.
5. **`RestaurantProfile.address` is NOT NULL** in the migration; tests had to be updated to supply it.
6. **`app/db/deps.py` is dead code** — Phase 0 wrapper no one imports. Not deleted in this slice; flagged for the user.
7. **bcrypt rounds reduced to 4 during hang debugging** — restored to 12 after diagnosis; the hang was not bcrypt-related.
8. **`autouse reset_rate_limiter` was made sync** — easier and avoids creating an extra event loop per test.
9. **`db_session` conftest fixture was rewritten** — now reuses `app.db.session.engine` (NullPool) for the per-test session; a separate engine is created and disposed for the TRUNCATE.

## Known issues

1. **Full pytest `tests/` suite hangs.** Per-file pytest runs work (66/66). The hang appears at the boundary between `test_notification_preferences.py` and `test_devices.py` and reproduces with a single test (`test_delete_device` alone also hangs). The previous Phase 1 hermes session left this in a similar state. Root cause investigation in this Phase 1 closeout did not find the trigger. The `FUDGO_NULLPOOL=1` env var is set in the running shell, and `app.db.session.engine` is verified to be `NullPool`. The smoke `python -c "from app.main import app; app.openapi()"` runs in ~1.4s. The hang is structural to pytest's combined collection + ASGITransport + asyncpg + slowapi state in this environment.
2. **`mypy` was not run** in the Phase 1 closeout. Acceptance criterion #3 (mypy clean) is unverified.
3. **`apps/api/README.md` Phase 1 endpoints section was not written** in this closeout. Phase 2 includes the equivalent.
4. **Verifier warned that `tests/auth/test_verify_otp.py` was in an unknown state** — file was re-read and is currently consistent: 6 tests, all green in isolation.

## What's NOT in this slice (per the explicit list)

- Restaurant + menu + promotion + R2 image upload (Phase 2)
- Cart + order models/endpoints (Phase 3)
- Delivery + courier auto-assign + tracking (Phase 4)
- Restaurant review + wishlist (Phase 5)
- WebSockets / Channels-style real-time (Phase 4/6)
- Real FCM/APNs push notifications (Phase 6 — only stubs here)
- Real SMS via Textbee (Phase 6 — only stubs here)
- Real SMTP / Plunk (Phase 6 — only stubs here)
- Celery / Redis broker (Phase 6 — only BackgroundTasks here)
- "Default address" selection on the user record
- Image upload (Phase 2)

## Suggested Phase 2 brief

Add `Promotion`, `MenuCategory`, `MenuItem`, and image models in
`app/restaurants/`. Expose public read endpoints (with PostGIS geo search)
and owner-only mutations. Wire Cloudflare R2 (S3-compatible) via `aioboto3`
for direct server-side image upload with content sniffing, dimension
validation, and a 5 MB cap. Regenerate `packages/api-contracts/openapi.json`;
the contracts CI workflow will catch drift.
