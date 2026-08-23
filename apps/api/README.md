# Fudgo API

Ground-up rewrite of the Fudz food-delivery backend from Django/DRF to
FastAPI + SQLModel + PostGIS. The Django original lives at
[`Fudz_api`](https://github.com/nyayo/Fudz_api) (read-only reference). This
repo is the clean-slate successor — no v1 migration cruft.

See [`FUDZ_V2_ANALYSIS.md`](FUDZ_V2_ANALYSIS.md) for the full v1→v2 analysis,
decision log, and phase roadmap.

## Status

**Phase 0 (Foundation): complete.** The app boots, connects to a PostGIS
Postgres database, runs Alembic migrations, and exposes health, docs, and
metrics endpoints. Phase 1 (Auth + Users) is next.

## Dev quickstart

```bash
# 1. Start db + redis (use an env file copied from .env.example)
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d db redis

# 2. Apply migrations (needs a reachable DB)
uv sync
uv run alembic upgrade head

# 3. Run the app (dev reload; omit --reload in prod)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

Optionally run everything in containers:

```bash
docker compose -f docker-compose.dev.yml up --build
```

## Environment variables

A template lives in `.env.example` (the real `.env` is gitignored).

| Variable              | Default        | Purpose                                   |
| --------------------- | -------------- | ----------------------------------------- |
| `ENVIRONMENT`         | `development`  | deployment | staging | production      |
| `DEBUG`               | `False`        | fastapi debug                             |
| `LOG_LEVEL`           | `INFO`         | stdlib/structlog level                    |
| `HOST` / `PORT`       | `0.0.0.0`/`8002` | bind                                      |
| `DB_HOST/PORT/USER/PASSWORD/NAME` | required | PostGIS Postgres               |
| `DB_SSLMODE`          | `prefer`       | libpq-style sslmode                       |
| `REDIS_HOST/PORT/DB`  | `redis/6379/0` | cache/broker                              |
| `JWT_*` (Phase 1)     | placeholders   | custom JWT signing                        |
| `GOOGLE_CLIENT_*` (Phase 1) | "" | OAuth                                |

## Endpoints

| Method | Path             | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| GET    | `/health`        | live + ready (DB) convenience    |
| GET    | `/health/live`   | liveness (no DB)                 |
| GET    | `/health/ready`  | readiness (runs SELECT 1 + write)|
| GET    | `/api/v2/`       | discovery                        |
| GET    | `/metrics`       | Prometheus text                  |
| GET    | `/docs`          | Swagger UI                       |
| GET    | `/redoc`         | ReDoc                            |

## Phase 1 endpoints (auth + users)

| Method | Path | Auth |
| --- | --- | --- |
| POST | /api/v2/auth/request-otp | none |
| POST | /api/v2/auth/verify-otp | none |
| POST | /api/v2/auth/phone/request-otp | none |
| POST | /api/v2/auth/phone/verify-otp | none |
| POST | /api/v2/auth/register | none |
| POST | /api/v2/auth/google | none |
| POST | /api/v2/auth/link-google | bearer |
| POST | /api/v2/auth/logout | bearer |
| POST | /api/v2/auth/logout-all | bearer |
| POST | /api/v2/auth/refresh | none |
| GET  | /api/v2/auth/profile | bearer |
| PATCH| /api/v2/auth/profile | bearer |
| POST | /api/v2/auth/password-reset | none |
| POST | /api/v2/auth/password-reset/confirm | none |
| GET  | /api/v2/auth/notification-preferences | bearer |
| PATCH| /api/v2/auth/notification-preferences | bearer |
| POST | /api/v2/auth/devices | bearer |
| DELETE| /api/v2/auth/devices/{id} | bearer |
| POST | /api/v2/auth/test-notification | bearer |
| GET  | /api/v2/users/addresses | bearer |
| POST | /api/v2/users/addresses | bearer |
| PATCH| /api/v2/users/addresses/{id} | bearer |
| DELETE| /api/v2/users/addresses/{id} | bearer |
| GET  | /api/v2/users/staff | bearer + role=restaurant |
| POST | /api/v2/users/staff | bearer + role=restaurant |
| PATCH| /api/v2/users/staff/{id} | bearer + role=restaurant |
| DELETE| /api/v2/users/staff/{id} | bearer + role=restaurant |

## Phase 2 endpoints (restaurants + menu + promotions + R2)

| Method | Path | Auth |
| --- | --- | --- |
| GET  | /api/v2/restaurants | none |
| GET  | /api/v2/restaurants/nearby | none |
| GET  | /api/v2/restaurants/{id} | none |
| PATCH| /api/v2/restaurants/{id} | bearer + role=restaurant |
| GET  | /api/v2/restaurants/{id}/categories | none |
| POST | /api/v2/restaurants/{id}/categories | bearer + owner |
| GET  | /api/v2/restaurants/{id}/categories/{cid} | none |
| PATCH| /api/v2/restaurants/{id}/categories/{cid} | bearer + owner |
| DELETE| /api/v2/restaurants/{id}/categories/{cid} | bearer + owner |
| POST | /api/v2/restaurants/{id}/categories/{cid}/image | bearer + owner |
| GET  | /api/v2/restaurants/{id}/items | none |
| GET  | /api/v2/restaurants/{id}/categories/{cid}/items | none |
| POST | /api/v2/restaurants/{id}/categories/{cid}/items | bearer + owner |
| GET  | /api/v2/restaurants/{id}/categories/{cid}/items/{iid} | none |
| PATCH| /api/v2/restaurants/{id}/categories/{cid}/items/{iid} | bearer + owner |
| DELETE| /api/v2/restaurants/{id}/categories/{cid}/items/{iid} | bearer + owner |
| POST | /api/v2/restaurants/{id}/categories/{cid}/items/{iid}/images | bearer + owner |
| GET  | /api/v2/restaurants/{id}/categories/{cid}/items/{iid}/images | none |
| DELETE| /api/v2/restaurants/{id}/categories/{cid}/items/{iid}/images/{img_id} | bearer + owner |
| POST | /api/v2/restaurants/{id}/categories/{cid}/items/{iid}/promotions | bearer + owner |
| DELETE| /api/v2/restaurants/{id}/categories/{cid}/items/{iid}/promotions/{pid} | bearer + owner |
| GET  | /api/v2/restaurants/{id}/promotions | none |
| POST | /api/v2/restaurants/{id}/promotions | bearer + owner |
| GET  | /api/v2/restaurants/{id}/promotions/{pid} | none |
| PATCH| /api/v2/restaurants/{id}/promotions/{pid} | bearer + owner |
| DELETE| /api/v2/restaurants/{id}/promotions/{pid} | bearer + owner |
| POST | /api/v2/restaurants/{id}/promotions/{pid}/toggle-active | bearer + owner |
| POST | /api/v2/restaurants/{id}/promotions/{pid}/banner | bearer + owner |
| DELETE| /api/v2/restaurants/{id}/promotions/{pid}/banner | bearer + owner |
| GET  | /api/v2/restaurants/{id}/promotions/{pid}/menu-items | none |
| GET  | /api/v2/menu-items | none |
| GET  | /api/v2/menu-items/{id} | none |
| GET  | /api/v2/promotions | none |
| GET  | /api/v2/promotions/active | none |
| GET  | /api/v2/promotions/{id} | none |
