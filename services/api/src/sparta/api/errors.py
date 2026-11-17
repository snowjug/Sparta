"""Error envelope and exception handlers.

Every error response has the shape ``{"error": {"code", "message", "trace_id", "details"}}``. Messages are written for
the owner, never echo user input and never include internals; the trace id (the request id) lets support find the log
line without exposing anything.
"""

import http
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from sparta.logging_setup import correlation_id_var
from sparta.providers.base import ProviderError
from sparta.services.errors import ProviderUnavailableError, RateLimited, ServiceError

log = logging.getLogger("sparta.api")

STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    408: "request_timeout",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "provider_unavailable",
}
_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    trace_id: str
    details: list[ErrorDetail] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope, "description": STATUS_CODES[status].replace("_", " ").capitalize()}
    for status in (401, 403, 404, 409, 413, 415, 422, 429, 503)
}


def error_response(
    status: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "trace_id": correlation_id_var.get() or "",
            "details": details,
        }
    }
    return JSONResponse(body, status_code=status, headers=headers)


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for error in exc.errors()[:20]:
        loc = [str(p) for p in error.get("loc", ())]
        if loc and loc[0] in _LOCATION_PREFIXES:
            loc = loc[1:]
        message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
        details.append({"field": ".".join(loc) or "body", "message": message[:200]})
    return details


async def _service_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimited):
        headers["Retry-After"] = str(max(1, exc.retry_after_s))
    if exc.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return error_response(exc.status, exc.code, exc.message, details=exc.details, headers=headers or None)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, "validation_error", "The request is not valid.", details=_validation_details(exc))


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = STATUS_CODES.get(exc.status_code, "http_error")
    try:
        message = http.HTTPStatus(exc.status_code).phrase
    except ValueError:
        message = "Request failed"
    headers = dict(exc.headers) if exc.headers else None
    if exc.status_code == 401:
        headers = {**(headers or {}), "WWW-Authenticate": "Bearer"}
    return error_response(exc.status_code, code, message, headers=headers)


async def _provider_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProviderError)
    log.warning("provider error", extra={"provider": exc.provider, "stage": exc.stage})
    unavailable = ProviderUnavailableError("An external service this feature needs is not available right now.")
    return error_response(unavailable.status, unavailable.code, unavailable.message)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(ProviderError, _provider_error)
