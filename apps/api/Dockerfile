# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

FROM python:3.12-slim
WORKDIR /app/apps/api
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libmagic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/.venv /opt/venv
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
