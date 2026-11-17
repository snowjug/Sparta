"""Pure-ASGI middleware (no ``BaseHTTPMiddleware``: it breaks WebSockets, streaming and context variables).

Order, outermost first: request context -> security headers -> trusted hosts -> CORS -> error guard -> body limit.
Putting the error guard inside CORS means even unexpected 500s carry CORS headers, so a browser reports the real error
instead of an opaque network failure.
"""

import logging
import re
import secrets
import time
from collections.abc import MutableMapping
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sparta.api.errors import error_response
from sparta.logging_setup import correlation_id_var

log = logging.getLogger("sparta.http")
REQUEST_ID = re.compile(r"[A-Za-z0-9._\-]{8,64}")
DOCS_PATHS = ("/docs", "/redoc")

SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "microphone=(), camera=(), geolocation=(), payment=()",
    # Responses carry personal data (transcripts, caller labels): nothing may be cached by browsers or proxies.
    "cache-control": "no-store",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
HSTS = "max-age=63072000; includeSubDomains"


class RequestContextMiddleware:
    """Assigns the request id (echoing a sane client-supplied one), logs one access line, never the query string."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get("x-request-id", "")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else secrets.token_hex(8)
        token = correlation_id_var.set(request_id)
        started = time.perf_counter()
        status = 0

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers.append("X-Request-ID", request_id)
                rate = scope.get("state", {}).get("rate_limit")
                if rate is not None:
                    headers["X-RateLimit-Limit"] = str(rate[0])
                    headers["X-RateLimit-Remaining"] = str(rate[1])
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["type"] == "http":
                log.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    },
                )
            correlation_id_var.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        docs = path.startswith(DOCS_PATHS)

        async def send_secure(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
                if not docs and "content-security-policy" not in headers:
                    headers["content-security-policy"] = API_CSP
                if self.hsts:
                    headers["strict-transport-security"] = HSTS
            await send(message)

        await self.app(scope, receive, send_secure)


class ErrorGuardMiddleware:
    """Last-resort handler: turns an unexpected exception into the standard 500 envelope (details only in the log)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            log.exception("unhandled error", extra={"method": scope.get("method"), "path": scope.get("path")})
            if started:
                raise
            response = error_response(500, "internal_error", "Something went wrong on our side. Please try again.")
            await response(scope, receive, send)


class BodyLimitMiddleware:
    """Bounds request bodies before any parsing. Uploads get their own (larger) limit; webhooks theirs."""

    def __init__(self, app: ASGIApp, *, default_limit: int, audio_limit: int, webhook_limit: int) -> None:
        self.app = app
        self.default_limit = default_limit
        self.audio_limit = audio_limit
        self.webhook_limit = webhook_limit

    def _limit_for(self, scope: MutableMapping[str, Any]) -> int:
        path = str(scope.get("path", ""))
        if "/webhooks/" in path:
            return self.webhook_limit
        if scope.get("method") == "POST" and path.endswith("/audio"):
            return self.audio_limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            response = error_response(
                413, "payload_too_large", f"The request is larger than the {limit // 1000} KB limit."
            )
            await response(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:  # chunked bodies have no Content-Length to check up front
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, limited_receive, send)
