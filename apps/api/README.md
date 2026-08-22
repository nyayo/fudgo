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
