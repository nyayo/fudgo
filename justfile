"""Fudgo monorepo recipes.

Install / lint / test / migrate / boot the API. Contracts pipeline lives at the
bottom. ``just`` is the runner; install it from https://just.systems.
"""

set dotenv-load

_default := env_var_or_default("ENVIRONMENT", "development")

# --- api (FastAPI backend) ----------------------------------------------------

api-install:
    cd apps/api && uv sync

api-lint:
    cd apps/api && uv run ruff check .
    cd apps/api && uv run ruff format --check .
    cd apps/api && uv run mypy app

api-test:
    cd apps/api && DB_HOST=${DB_HOST:-localhost} DB_PORT=${DB_PORT:-5432} \
        DB_USER=${DB_USER:-fudgo} DB_PASSWORD=${DB_PASSWORD:-password} \
        DB_NAME=${DB_NAME:-fudgo} \
        uv run pytest -v --cov=app --cov-report=term-missing

api-migrate:
    cd apps/api && uv run alembic upgrade head

api-up:
    docker compose -f apps/api/docker-compose.dev.yml up --build

api-down:
    docker compose -f apps/api/docker-compose.dev.yml down -v

# --- contracts (OpenAPI pipeline) --------------------------------------------

contracts-generate:
    cd apps/api && uv sync
    uv run --project apps/api python tools/scripts/generate_openapi.py

contracts-check: contracts-generate
    @if [ -n "$(git status --porcelain packages/api-contracts/openapi.json)" ]; then \
        echo "OpenAPI drift detected. Run 'just contracts-generate' and commit the result."; \
        git diff -- packages/api-contracts/openapi.json; \
        exit 1; \
    else \
        echo "OpenAPI contract is up to date."; \
    fi