"""Prometheus scrape endpoint with IP restriction in production."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config.settings import settings
from app.observability.metrics import generate_metrics_text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def get_prometheus_metrics(request: Request) -> Response:
    """Expose Prometheus metrics for scraping.

    In production, restricted to allowed scraper IP addresses.
    """
    if not settings.PROMETHEUS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prometheus metrics are disabled",
        )

    # In production, enforce IP allowlist
    if settings.is_production:
        client_ip = request.client.host if request.client else ""
        allowed_ips = settings.prometheus_allowed_ips_list
        if client_ip not in allowed_ips:
            logger.warning(
                "Unauthorized Prometheus scrape attempt from IP %s (allowed: %s)",
                client_ip,
                allowed_ips,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to metrics endpoint is restricted to authorized scrapers",
            )

    data, content_type = generate_metrics_text()
    return Response(content=data, media_type=content_type)
