"""Operational endpoints (mounted at the root, outside ``/api/v1``): liveness, readiness and optional metrics."""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from sparta.api.deps import get_container
from sparta.services.errors import NotFound

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies, so a database outage does not restart the service."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: the hard dependencies (database schema, shared state) answer. A degraded telephony provider is
    reported but does not make the service unready, because the owner can still use everything else."""
    c = get_container(request)
    checks: dict[str, Any] = {
        "database": "ok" if await c.db.schema_ready() else "unavailable",
        "shared_state": "ok" if await c.kv.ping() else "unavailable",
    }
    status = await c.providers.telephony.status()
    checks["telephony"] = {"provider": status.provider, "healthy": status.healthy, "simulated": status.simulated}
    ready = checks["database"] == "ok" and checks["shared_state"] == "ok"
    return JSONResponse(
        {"status": "ready" if ready else "unavailable", "checks": checks}, status_code=200 if ready else 503
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    """Prometheus text. Off unless `SPARTA_EXPOSE_METRICS=true`; counters and timings only (no personal data), but still
    restrict the route to your monitoring network."""
    c = get_container(request)
    if not c.settings.expose_metrics:
        raise NotFound("Not found.")
    return PlainTextResponse(c.metrics.render_prometheus(), media_type="text/plain; version=0.0.4")
