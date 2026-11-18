"""Network checks for ``sparta doctor --online``.

Rules: free metadata requests only (token, voice list, model list, health probes, a signed read of the ACS number list);
anything that costs money lives in :mod:`sparta.doctor.billable` and needs ``--allow-billable``. Redirects are never
followed (the requests carry keys), response bodies are read with a hard cap, and no message contains a URL, a response
body or a key: only static, hand-written reasons.
"""

import asyncio
import base64
import contextlib
import json
import os
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from sparta.config import Settings
from sparta.db.session import Database
from sparta.doctor.checks import ACS, CORE, OPENAI, SPEECH, callback_host
from sparta.doctor.model import Check, Status
from sparta.preflight import check_database, check_redis
from sparta.providers.azure_common import https_origin, valid_region
from sparta.providers.tts.catalog import DEFAULT_VOICES

BODY_CAP = 1_000_000
PROBE_CALL_ID = "doctorprobe"
EVENTS_PATH = "/api/v1/webhooks/acs/events"
MEDIA_PATH = "/api/v1/media/acs/" + PROBE_CALL_ID


class Unreachable(Exception):
    """A network failure with a static, safe reason (never the exception text: it can carry URLs)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    headers: httpx.Headers

    def json(self) -> object:
        try:
            return json.loads(self.body)
        except ValueError:
            return None


def _reason(exc: BaseException) -> str:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return "the TLS certificate could not be verified"
        if isinstance(current, socket.gaierror):
            return "the host name was not found"
        if isinstance(current, ConnectionRefusedError):
            return "the connection was refused"
        current = current.__cause__ or current.__context__
    if isinstance(exc, httpx.TimeoutException):
        return "the request timed out"
    return "a network error occurred"


async def fetch(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float = 8.0,
) -> Reply:
    """One bounded request. Raises :class:`Unreachable` for transport failures; the status is never raised on."""
    try:
        request = http.build_request(method, url, headers=headers, content=content, timeout=timeout_s)
        response = await http.send(request, stream=True, follow_redirects=False)
    except (httpx.HTTPError, OSError) as exc:
        raise Unreachable(_reason(exc)) from None
    body = bytearray()
    try:
        async for piece in response.aiter_bytes():
            body += piece
            if len(body) > BODY_CAP:
                break
    except (httpx.HTTPError, OSError) as exc:
        raise Unreachable(_reason(exc)) from None
    finally:
        await response.aclose()
    return Reply(response.status_code, bytes(body[:BODY_CAP]), response.headers)


# ----------------------------------------------------------------------------------------------------------- speech
def _speech_urls(settings: Settings) -> tuple[str, str] | None:
    """``(issueToken URL, voices list URL)`` for the configured region or custom-domain endpoint."""
    if settings.azure_speech_endpoint:
        base = https_origin(settings.azure_speech_endpoint)
        return (f"{base}/sts/v1.0/issueToken", f"{base}/tts/cognitiveservices/voices/list") if base else None
    region = valid_region(settings.azure_speech_region)
    if region is None:
        return None
    return (
        f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
    )


async def speech_online(settings: Settings, http: httpx.AsyncClient, timeout_s: float) -> list[Check]:
    urls = _speech_urls(settings)
    if urls is None or settings.azure_speech_key is None:
        return [
            Check(
                "speech.online",
                SPEECH,
                "Speech resource reachable",
                Status.BLOCKED,
                "skipped: the key or region is not configured.",
                "Set SPARTA_AZURE_SPEECH_KEY and SPARTA_AZURE_SPEECH_REGION first.",
            )
        ]
    token_url, voices_url = urls
    key = {"Ocp-Apim-Subscription-Key": settings.azure_speech_key.get_secret_value()}
    out: list[Check] = []
    try:
        token = await fetch(http, "POST", token_url, headers=key, content=b"", timeout_s=timeout_s)
    except Unreachable as exc:
        return [
            Check(
                "speech.token",
                SPEECH,
                "Speech key accepted",
                Status.BLOCKED,
                f"{exc.reason}.",
                "Check the region or custom endpoint and the network path.",
            )
        ]
    if token.status == 200:
        out.append(Check("speech.token", SPEECH, "Speech key accepted", Status.PASS, "a token was issued."))
    elif token.status in (401, 403):
        return [
            Check(
                "speech.token",
                SPEECH,
                "Speech key accepted",
                Status.BLOCKED,
                f"the service answered HTTP {token.status}: the key does not belong to this region or endpoint.",
                "Copy the key and region from the same Speech resource.",
            )
        ]
    else:
        out.append(
            Check(
                "speech.token",
                SPEECH,
                "Speech key accepted",
                Status.WARNING,
                f"unexpected HTTP {token.status} from the token service.",
                "Retry; check the Azure status page if it persists.",
            )
        )
    try:
        voices = await fetch(http, "GET", voices_url, headers=key, timeout_s=timeout_s)
    except Unreachable as exc:
        out.append(
            Check(
                "speech.voices",
                SPEECH,
                "Voices available in this region",
                Status.WARNING,
                f"{exc.reason}.",
                "Retry.",
            )
        )
        return out
    parsed = voices.json() if voices.status == 200 else None
    if not isinstance(parsed, list):
        out.append(
            Check(
                "speech.voices",
                SPEECH,
                "Voices available in this region",
                Status.WARNING,
                f"the voice list could not be read (HTTP {voices.status}).",
                "Retry.",
            )
        )
        return out
    names = {v.get("ShortName") for v in parsed if isinstance(v, dict)}
    missing = [f"{loc} {voice}" for loc, voice in sorted(DEFAULT_VOICES.items()) if voice not in names]
    if missing:
        out.append(
            Check(
                "speech.voices",
                SPEECH,
                "Voices available in this region",
                Status.BLOCKED,
                "the default voice is not offered here for: " + ", ".join(missing) + ".",
                "Use a region that offers en-IN, hi-IN and kn-IN neural voices (for example centralindia).",
            )
        )
    else:
        out.append(
            Check(
                "speech.voices",
                SPEECH,
                "Voices available in this region",
                Status.PASS,
                f"{len(names)} voices listed, including the default voice of every supported language.",
            )
        )
    return out


# ----------------------------------------------------------------------------------------------------------- openai
async def openai_online(settings: Settings, http: httpx.AsyncClient, timeout_s: float) -> list[Check]:
    base = https_origin(settings.azure_openai_endpoint)
    if base is None or settings.azure_openai_key is None:
        return [
            Check(
                "openai.online",
                OPENAI,
                "Model endpoint reachable",
                Status.BLOCKED,
                "skipped: the endpoint or key is not configured.",
                "Set SPARTA_AZURE_OPENAI_ENDPOINT and SPARTA_AZURE_OPENAI_KEY first.",
            )
        ]
    url = f"{base}/openai/models?api-version={quote(settings.azure_openai_api_version, safe='-')}"
    try:
        reply = await fetch(
            http, "GET", url, headers={"api-key": settings.azure_openai_key.get_secret_value()}, timeout_s=timeout_s
        )
    except Unreachable as exc:
        return [
            Check(
                "openai.models",
                OPENAI,
                "Model endpoint accepts the key",
                Status.BLOCKED,
                f"{exc.reason}.",
                "Check the endpoint and the network path.",
            )
        ]
    if reply.status == 200:
        return [
            Check(
                "openai.models",
                OPENAI,
                "Model endpoint accepts the key",
                Status.PASS,
                "the resource answered the model list. The deployment itself is only proven by --allow-billable.",
            )
        ]
    if reply.status in (401, 403):
        return [
            Check(
                "openai.models",
                OPENAI,
                "Model endpoint accepts the key",
                Status.BLOCKED,
                f"the service answered HTTP {reply.status}: the key does not belong to this endpoint.",
                "Copy the key and endpoint from the same Azure OpenAI resource.",
            )
        ]
    return [
        Check(
            "openai.models",
            OPENAI,
            "Model endpoint accepts the key",
            Status.WARNING,
            f"unexpected HTTP {reply.status}; the deployment is not proven.",
            "Run with --allow-billable to test the deployment with one tiny request.",
        )
    ]


# --------------------------------------------------------------------------------------------- stores
async def stores_online(settings: Settings) -> list[Check]:
    out: list[Check] = []
    problem = await check_database(settings.database_url)
    if problem:
        out.append(Check("db.connect", CORE, "Database reachable", Status.BLOCKED, problem))
    else:
        out.append(Check("db.connect", CORE, "Database reachable", Status.PASS, "answered SELECT 1."))
        database = Database(settings.database_url)
        try:
            state = await database.schema_state()
        finally:
            with contextlib.suppress(Exception):
                await database.dispose()
        out.append(
            Check(
                "db.schema",
                CORE,
                "Database schema",
                Status.PASS if state == "ok" else Status.BLOCKED,
                {
                    "ok": "the applied migrations match this code.",
                    "migrations_pending": "the database is older than this code.",
                    "unavailable": "the schema does not exist yet.",
                }[state],
                "" if state == "ok" else "Run `python -m sparta migrate`.",
            )
        )
    if settings.redis_url:
        problem = await check_redis(settings.redis_url)
        out.append(
            Check("redis.connect", CORE, "Redis reachable", Status.BLOCKED, problem)
            if problem
            else Check("redis.connect", CORE, "Redis reachable", Status.PASS, "answered PING.")
        )
    return out


# -------------------------------------------------------------------------------------------------- callbacks
def _ws_headers() -> dict[str, str]:
    return {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode("ascii"),
    }


async def callback_online(
    settings: Settings, http: httpx.AsyncClient, timeout_s: float, override: str | None
) -> list[Check]:
    origin = https_origin(override or settings.acs_callback_base_url)
    host = callback_host(settings, override)
    title = "Public callback URL answers"
    if origin is None or host is None:
        return [
            Check(
                "callback.health", ACS, title, Status.BLOCKED, "skipped: no valid https callback URL.", "Set it first."
            )
        ]
    out: list[Check] = []
    try:
        health = await fetch(http, "GET", f"{origin}/healthz", timeout_s=timeout_s)
    except Unreachable as exc:
        return [
            Check(
                "callback.health",
                ACS,
                title,
                Status.BLOCKED,
                f"{exc.reason}.",
                "Start the API, check the tunnel or the DNS name and the certificate.",
            )
        ]
    if health.status == 200:
        out.append(Check("callback.health", ACS, title, Status.PASS, "GET /healthz answered 200 over https."))
    elif health.status == 400:
        out.append(
            Check(
                "callback.health",
                ACS,
                title,
                Status.BLOCKED,
                "HTTP 400: the host header is probably not in SPARTA_TRUSTED_HOSTS.",
                "Add the callback host name to SPARTA_TRUSTED_HOSTS.",
            )
        )
        return out
    else:
        out.append(
            Check(
                "callback.health",
                ACS,
                title,
                Status.BLOCKED,
                f"GET /healthz answered HTTP {health.status}.",
                "Check what is serving this URL.",
            )
        )
        return out
    try:
        ready = await fetch(http, "GET", f"{origin}/readyz", timeout_s=timeout_s)
        parsed = ready.json()
        reasons = ""
        if isinstance(parsed, dict) and isinstance(parsed.get("checks"), dict):
            reasons = " (" + ", ".join(f"{k}: {v}" for k, v in parsed["checks"].items() if isinstance(v, str)) + ")"
        out.append(
            Check(
                "callback.ready",
                ACS,
                "Public API is ready",
                Status.PASS if ready.status == 200 else Status.BLOCKED,
                f"GET /readyz answered {ready.status}{reasons}.",
                "" if ready.status == 200 else "Fix the failing dependency, then retry.",
            )
        )
    except Unreachable as exc:
        out.append(Check("callback.ready", ACS, "Public API is ready", Status.BLOCKED, f"{exc.reason}."))
    out.append(await _webhook_auth(http, origin, timeout_s))
    out.append(await _media_auth(http, origin, timeout_s))
    out.append(
        Check(
            "callback.external",
            ACS,
            "Reachable from Azure's network",
            Status.UNVERIFIED,
            "the checks above ran from this machine. That Azure can reach the URL is only proven by a delivered event.",
            "Create the Event Grid subscription and place a call (docs/TELEPHONY.md, 'Live-test checklist').",
        )
    )
    return out


async def _webhook_auth(http: httpx.AsyncClient, origin: str, timeout_s: float) -> Check:
    title = "Event Grid endpoint demands authentication"
    try:
        reply = await fetch(
            http,
            "POST",
            f"{origin}{EVENTS_PATH}",
            headers={"Content-Type": "application/json"},
            content=b"[]",
            timeout_s=timeout_s,
        )
    except Unreachable as exc:
        return Check("callback.webhook_auth", ACS, title, Status.BLOCKED, f"{exc.reason}.")
    if reply.status == 401:
        return Check("callback.webhook_auth", ACS, title, Status.PASS, "an unauthenticated delivery was refused (401).")
    if reply.status == 404:
        return Check(
            "callback.webhook_auth",
            ACS,
            title,
            Status.BLOCKED,
            "404: this deployment does not serve the ACS routes (SPARTA_TELEPHONY_PROVIDER is not azure there) or "
            "it is not Sparta.",
            "Deploy with SPARTA_TELEPHONY_PROVIDER=azure.",
        )
    if 200 <= reply.status < 300:
        return Check(
            "callback.webhook_auth",
            ACS,
            title,
            Status.BLOCKED,
            "an UNAUTHENTICATED delivery was accepted.",
            "Do not expose this deployment: the Event Grid verifier is not active.",
        )
    return Check(
        "callback.webhook_auth",
        ACS,
        title,
        Status.WARNING,
        f"unexpected HTTP {reply.status} for an unauthenticated delivery.",
        "Check the deployment's logs.",
    )


async def _media_auth(http: httpx.AsyncClient, origin: str, timeout_s: float) -> Check:
    title = "Media WebSocket demands authentication"
    try:
        reply = await fetch(http, "GET", f"{origin}{MEDIA_PATH}", headers=_ws_headers(), timeout_s=timeout_s)
    except Unreachable as exc:
        return Check("callback.media_auth", ACS, title, Status.BLOCKED, f"{exc.reason}.")
    if reply.status in (401, 403):
        return Check(
            "callback.media_auth",
            ACS,
            title,
            Status.PASS,
            f"a WebSocket upgrade without a token was refused ({reply.status}); the path reaches the API.",
        )
    if reply.status == 101:
        return Check(
            "callback.media_auth",
            ACS,
            title,
            Status.BLOCKED,
            "a WebSocket upgrade WITHOUT a token was accepted.",
            "Do not expose this deployment: the media verifier is not active.",
        )
    return Check(
        "callback.media_auth",
        ACS,
        title,
        Status.BLOCKED if reply.status in (404, 426) else Status.WARNING,
        f"the upgrade request was answered HTTP {reply.status}: the proxy may not forward WebSockets.",
        "Make sure the ingress or tunnel supports WebSockets on /api/v1/media/.",
    )


# ------------------------------------------------------------------------------------------------------- oidc
async def oidc_online(settings: Settings, http: httpx.AsyncClient, timeout_s: float) -> list[Check]:
    if settings.auth_mode != "oidc":
        return []
    url = https_origin(settings.oidc_jwks_url)
    if url is None and settings.oidc_issuer:
        issuer = https_origin(settings.oidc_issuer)
        url = f"{issuer}/.well-known/jwks.json" if issuer else None
    title = "Identity provider signing keys"
    if url is None:
        return [Check("oidc.jwks", CORE, title, Status.BLOCKED, "no https JWKS URL could be derived.")]
    try:
        reply = await fetch(http, "GET", url, timeout_s=timeout_s)
    except Unreachable as exc:
        return [Check("oidc.jwks", CORE, title, Status.BLOCKED, f"{exc.reason}.")]
    parsed = reply.json() if reply.status == 200 else None
    keys = parsed.get("keys") if isinstance(parsed, dict) else None
    if isinstance(keys, list) and any(isinstance(k, dict) and k.get("kty") == "RSA" for k in keys):
        return [Check("oidc.jwks", CORE, title, Status.PASS, f"{len(keys)} signing key(s) published.")]
    return [
        Check(
            "oidc.jwks",
            CORE,
            title,
            Status.BLOCKED,
            f"HTTP {reply.status}: no RSA signing key could be read.",
            "Check SPARTA_OIDC_JWKS_URL or SPARTA_OIDC_ISSUER.",
        )
    ]


async def run_online(
    settings: Settings,
    *,
    azure: bool,
    callback_url: str | None,
    http: httpx.AsyncClient,
    timeout_s: float,
) -> list[Check]:
    """Every free network check, run concurrently. A failing probe becomes a check, never an exception."""
    jobs: list[asyncio.Future[list[Check]] | asyncio.Task[list[Check]]] = [
        asyncio.ensure_future(stores_online(settings)),
        asyncio.ensure_future(oidc_online(settings, http, timeout_s)),
    ]
    if azure:
        jobs += [
            asyncio.ensure_future(speech_online(settings, http, timeout_s)),
            asyncio.ensure_future(callback_online(settings, http, timeout_s, callback_url)),
        ]
        if settings.llm_provider == "azure_openai":
            jobs.append(asyncio.ensure_future(openai_online(settings, http, timeout_s)))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    out: list[Check] = []
    for result in results:
        if isinstance(result, BaseException):
            out.append(
                Check(
                    "doctor.internal",
                    CORE,
                    "A network check failed unexpectedly",
                    Status.WARNING,
                    f"internal error of type {type(result).__name__}.",
                    "Report this as a bug in `sparta doctor`.",
                )
            )
        else:
            out.extend(result)
    return out


__all__ = [
    "Reply",
    "Unreachable",
    "fetch",
    "run_online",
    "urlsplit",
]
