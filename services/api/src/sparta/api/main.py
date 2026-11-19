"""Application factory.

``create_app()`` builds the FastAPI app. Run it with ``uvicorn sparta.api.main:create_app --factory`` (or
``python -m sparta serve``). Tests pass an already built, hermetic ``Container`` so no lifespan or background job runs.
"""

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.formparsers import MultiPartParser
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sparta import __version__
from sparta.api import errors
from sparta.api.auth import build_authenticator
from sparta.api.errors import ERROR_RESPONSES
from sparta.api.middleware import (
    BodyLimitMiddleware,
    ErrorGuardMiddleware,
    ProviderOnlyHostsMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from sparta.api.routers import account, calls, health, live, safety, screening, simulator, system, webhooks
from sparta.config import Settings, get_settings
from sparta.logging_setup import configure_logging
from sparta.observability.tracing import setup_tracing
from sparta.services.container import Container
from sparta.services.jobs import BackgroundJobs
from sparta.telephony.webhooks import EVENT_GRID_MAX_BYTES

log = logging.getLogger("sparta.api")
API_PREFIX = "/api/v1"
UPLOAD_OVERHEAD_BYTES = 64 * 1024

DESCRIPTION = """
Sparta screens calls with an AI assistant that always says it is an AI, refuses requests for protected information and
explains every decision. Errors share one envelope: `{"error": {"code", "message", "trace_id", "details"}}`.

**Development mode** has no credentials; clients must show a *Development identity* banner (`/system/status`).
**Provider callbacks** (`/webhooks/*`, `/media/*`) are not part of this document.
"""
TAGS = [
    {"name": "system", "description": "Deployment capabilities, the signed-in owner and the Home summary."},
    {"name": "calls", "description": "Create and drive calls, owner actions, feedback, export and deletion."},
    {"name": "live", "description": "WebSocket tickets and live events."},
    {"name": "account", "description": "Preferences, assistant profile, voices and personal-voice consent."},
    {"name": "safety", "description": "Policies, safety events, trusted/blocked callers, audit trail."},
    {"name": "simulator", "description": "Simulator Lab: scenarios, simulated calls, deterministic replay."},
    {"name": "screening", "description": "Native Android call screening."},
    {"name": "health", "description": "Liveness, readiness and metrics (root paths)."},
]


def _operation_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "api"
    return f"{tag}_{route.name}"


def _own_telemetry_only() -> dict[str, Any]:
    """FastAPI 0.16x instruments itself with OpenTelemetry whenever a global provider exists (that is, with OTLP set up).
    Its spans carry the raw URL path and query string (a history search term is content), adopt a trace id chosen by the
    caller's ``traceparent`` header and duplicate the request span in ``api/middleware.py``, so they are turned off:
    Sparta's own spans are the only ones. Older FastAPI versions have no such option and no such behaviour."""
    if "telemetry" not in inspect.signature(FastAPI.__init__).parameters:
        return {}
    off = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}
    return {"telemetry": off}


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container is not None else get_settings())
    owns_container = container is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http: httpx.AsyncClient | None = None
        jobs: BackgroundJobs | None = None
        if owns_container:
            configure_logging(settings.log_level, settings.log_json)
            setup_tracing(settings)
            built = await Container.build(settings)
            await built.start()
            await built.warm_up()  # best effort and logged: the first call must not pay for it
            app.state.container = built
            http = httpx.AsyncClient(timeout=5.0, follow_redirects=False)
            app.state.authenticator = build_authenticator(settings, http)
            jobs = BackgroundJobs(
                calls=built.calls,
                retention=built.retention,
                reaper_interval_s=settings.reaper_interval_s,
                retention_interval_s=settings.retention_job_interval_s,
            )
            jobs.start()
            if settings.auth_mode == "dev":
                log.warning("development identity is active: anyone who can reach this server acts as the owner")
            log.info("sparta api started", extra={"version": __version__, "env": settings.env.value})
        try:
            yield
        finally:
            if jobs is not None:
                await jobs.stop()
            if owns_container:
                await app.state.container.stop()
            if http is not None:
                await http.aclose()

    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Sparta API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
        generate_unique_id_function=_operation_id,
        **_own_telemetry_only(),
    )
    app.state.settings = settings
    app.state.known_users = set()
    app.state.user_locks = {}  # serialises the first request(s) of a new owner so provisioning runs once per process
    if container is not None:
        app.state.container = container
        app.state.authenticator = build_authenticator(settings, None)
    else:
        # Replaced during startup with the real authenticator; this keeps `create_app()` usable for schema export.
        app.state.authenticator = build_authenticator(settings, None)

    # Uploaded audio is processed in memory only. Starlette spills multipart files larger than 1 MiB to a temporary
    # file, so raise that threshold above our own upload limit: a permitted upload never touches the disk.
    MultiPartParser.spool_max_size = settings.max_audio_bytes + UPLOAD_OVERHEAD_BYTES

    errors.install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for module in (system, calls, live, account, safety, simulator, screening, webhooks):
        api.include_router(module.router)
    api.include_router(webhooks.media_router)
    app.include_router(api)
    app.include_router(health.router)

    # Added innermost first; the last one added is the outermost layer.
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=settings.max_request_bytes,
        audio_limit=settings.max_audio_bytes + UPLOAD_OVERHEAD_BYTES,
        webhook_limit=EVENT_GRID_MAX_BYTES + UPLOAD_OVERHEAD_BYTES,
    )
    app.add_middleware(ErrorGuardMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "X-Sparta-Dev-User"],
        expose_headers=[
            "X-Request-ID",
            "Retry-After",
            "Content-Disposition",
            "Idempotent-Replayed",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
        max_age=600,
    )
    if settings.provider_only_hosts:
        app.add_middleware(ProviderOnlyHostsMiddleware, hosts=settings.provider_only_hosts)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    return app
