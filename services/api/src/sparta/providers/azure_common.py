"""Plumbing shared by the Azure REST adapters (Speech, OpenAI): endpoint validation and sanitised HTTP errors.

``ProviderError.message`` is shown to owners and written to logs, so nothing here ever puts a response body, a URL or a
credential into an error message. Nothing in this module has been exercised against a live Azure service.
"""

import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from sparta.providers.base import ProviderError, ProviderRejected, ProviderTimeout

MAX_RETRY_AFTER_S = 5.0  # a hostile or buggy Retry-After must not park a live call (ResilientCaller caps again at 2 s)
MAX_RESPONSE_BYTES = 4_000_000
_REGION = re.compile(r"[a-z0-9]{2,32}")
_HOST = re.compile(r"[A-Za-z0-9.-]+")


def https_origin(value: str | None) -> str | None:
    """``value`` as a normalised ``https://host[:port][/prefix]`` base URL, or ``None`` when it is not a safe one.

    Credentials are sent to this URL, so plain http, embedded credentials, queries and fragments are all refused.
    """
    if not value or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname
        _ = parts.port  # raises ValueError for an invalid port
    except ValueError:
        return None
    if parts.scheme != "https" or not host or not _HOST.fullmatch(host):
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    return f"https://{parts.netloc}{parts.path.rstrip('/')}"


def valid_region(region: str | None) -> str | None:
    """A lower-case Azure region name that is safe to put in a host name, else ``None``."""
    value = (region or "").strip().lower()
    return value if _REGION.fullmatch(value) else None


def _number(raw: str) -> float | None:
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _bounded(seconds: float) -> float:
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S)


def retry_after_seconds(response: httpx.Response, now: datetime) -> float | None:
    """The server's back-off hint in seconds (``retry-after-ms``, delta seconds or an HTTP date), bounded."""
    raw_ms = response.headers.get("retry-after-ms")
    if raw_ms is not None and (millis := _number(raw_ms)) is not None:
        return _bounded(millis / 1000.0)
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    if (seconds := _number(raw)) is None:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        seconds = (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp() - now.timestamp()
    return _bounded(seconds)


def error_for_status(
    provider: str, stage: str, status: int, retry_after_s: float | None = None
) -> ProviderError | None:
    """``None`` for a 2xx response, otherwise the sanitised error for ``status``."""
    if 200 <= status < 300:
        return None
    if status in (401, 403):
        return ProviderRejected(provider, stage, "authentication failed", status=status)
    if status in (400, 415, 422):
        return ProviderRejected(provider, stage, f"request rejected (HTTP {status})", status=status)
    if status == 413:
        return ProviderRejected(provider, stage, "payload too large", status=status)
    if status == 404:
        return ProviderError(provider, stage, "endpoint not found (check region, endpoint or deployment)", status=404)
    if status == 429:
        return ProviderError(
            provider, stage, "rate limited", retryable=True, status=status, retry_after_s=retry_after_s
        )
    if status == 408 or status >= 500:
        message = f"service unavailable (HTTP {status})"
        return ProviderError(provider, stage, message, retryable=True, status=status, retry_after_s=retry_after_s)
    return ProviderError(provider, stage, f"unexpected response (HTTP {status})", status=status)


def error_for_transport(provider: str, stage: str, exc: BaseException, timeout_s: float) -> ProviderError:
    """Map an httpx/OS failure to a sanitised error. ``str(exc)`` can contain URLs, so it is never used."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeout(provider, stage, timeout_s)
    return ProviderError(provider, stage, "network error", retryable=True)


async def send_bounded(
    http: httpx.AsyncClient,
    request: httpx.Request,
    *,
    provider: str,
    stage: str,
    timeout_s: float,
    cap: int = MAX_RESPONSE_BYTES,
) -> tuple[httpx.Response, bytes]:
    """Send ``request`` without following redirects and read at most ``cap`` body bytes.

    Redirects are never followed because the request carries a subscription key. The status is NOT checked here.
    """
    try:
        response = await http.send(request, stream=True, follow_redirects=False)
    except (httpx.HTTPError, OSError) as exc:
        raise error_for_transport(provider, stage, exc, timeout_s) from None
    body = bytearray()
    try:
        async for piece in response.aiter_bytes():
            body += piece
            if len(body) > cap:
                raise ProviderError(provider, stage, "response too large", status=response.status_code)
    except (httpx.HTTPError, OSError) as exc:
        raise error_for_transport(provider, stage, exc, timeout_s) from None
    finally:
        await response.aclose()
    return response, bytes(body)
