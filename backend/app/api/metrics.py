"""Publish the metric definitions that drive the UI's tooltips."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import MetricsOut, metrics_payload

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsOut)
def metrics() -> MetricsOut:
    """Every metric's definition, denominator and caveats.

    Served from the same registry the computation uses, so a metric cannot appear in the
    product with a stale or missing definition.
    """
    return metrics_payload()
