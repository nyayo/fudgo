"""Prometheus instrumentation via prometheus-fastapi-instrumentator.

Exposes ``/metrics`` with the default HTTP histogram. Health and metrics
endpoints are excluded from the histogram to keep the signal clean.
"""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app: FastAPI) -> None:
    """Instrument the app and expose /metrics (excluded from the OpenAPI schema)."""
    Instrumentator(
        excluded_handlers=["/health", "/health/live", "/health/ready", "/metrics"]
    ).instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )
