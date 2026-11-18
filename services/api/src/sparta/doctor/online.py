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
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from sparta.config import Settings
from sparta.db.session import Database
from sparta.doctor.checks import ACS, CORE, OPENAI, SPEECH, TWILIO
from sparta.doctor.model import Check, Status
from sparta.preflight import check_database, check_redis
from sparta.providers.azure_common import https_origin, valid_region
from sparta.providers.tts.catalog import DEFAULT_VOICES
from sparta.services.numbers import mask_number

BODY_CAP = 1_000_000
PROBE_CALL_ID = "doctorprobe"
EVENTS_PATH = "/api/v1/webhooks/acs/events"
MEDIA_PATH = "/api/v1/media/acs/" + PROBE_CALL_ID
TWILIO_VOICE_PATH = "/api/v1/webhooks/twilio/voice"
TWILIO_MEDIA_PATH = "/api/v1/media/twilio/" + PROBE_CALL_ID
TWILIO_API = "https://api.twilio.com/2010-04-01"


class Unreachable(Exception):
    """A network failure with a static, safe reason (never the exception text: it can carry URLs)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _remote_text(value: str, limit: int = 40) -> str:
    """Text a remote server sent, reduced to plain printable ASCII and a short length before it is shown."""
    return "".join(ch if ch.isascii() and ch.isprintable() else "?" for ch in value)[:limit]


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
    settings: Settings,
    http: httpx.AsyncClient,
    timeout_s: float,
    override: str | None,
    provider: str = "azure",
) -> list[Check]:
    twilio = provider == "twilio"
    group, prefix = (TWILIO, "twilio_callback") if twilio else (ACS, "callback")
    configured = settings.twilio_callback_base_url if twilio else settings.acs_callback_base_url
    origin = https_origin(override or configured)
    title = "Public callback URL answers"
    if origin is None:
        return [
            Check(
                f"{prefix}.health",
                group,
                title,
                Status.BLOCKED,
                "skipped: no valid https callback URL.",
                "Set it first.",
            )
        ]
    out: list[Check] = []
    try:
        health = await fetch(http, "GET", f"{origin}/healthz", timeout_s=timeout_s)
    except Unreachable as exc:
        return [
            Check(
                f"{prefix}.health",
                group,
                title,
                Status.BLOCKED,
                f"{exc.reason}.",
                "Start the API, check the tunnel or the DNS name and the certificate.",
            )
        ]
    if health.status == 200:
        out.append(Check(f"{prefix}.health", group, title, Status.PASS, "GET /healthz answered 200 over https."))
    elif health.status == 400:
        out.append(
            Check(
                f"{prefix}.health",
                group,
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
                f"{prefix}.health",
                group,
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
            shown = [(k, v) for k, v in parsed["checks"].items() if isinstance(k, str) and isinstance(v, str)]
            reasons = " (" + ", ".join(f"{_remote_text(k)}: {_remote_text(v)}" for k, v in shown[:12]) + ")"
        out.append(
            Check(
                f"{prefix}.ready",
                group,
                "Public API is ready",
                Status.PASS if ready.status == 200 else Status.BLOCKED,
                f"GET /readyz answered {ready.status}{reasons}.",
                "" if ready.status == 200 else "Fix the failing dependency, then retry.",
            )
        )
    except Unreachable as exc:
        out.append(Check(f"{prefix}.ready", group, "Public API is ready", Status.BLOCKED, f"{exc.reason}."))
    out.append(await (_twilio_webhook_auth if twilio else _webhook_auth)(http, origin, timeout_s))
    out.append(await _media_auth(http, origin, timeout_s, twilio=twilio))
    who = "Twilio's" if twilio else "Azure's"
    out.append(
        Check(
            f"{prefix}.external",
            group,
            f"Reachable from {who} network",
            Status.UNVERIFIED,
            f"the checks above ran from this machine. That {'Twilio' if twilio else 'Azure'} can reach the URL is only "
            "proven by a delivered call.",
            "Point the number at the URL and place a call (docs/TELEPHONY.md, 'Live-test checklist')."
            if twilio
            else "Create the Event Grid subscription and place a call (docs/TELEPHONY.md, 'Live-test checklist').",
        )
    )
    return out


async def _twilio_webhook_auth(http: httpx.AsyncClient, origin: str, timeout_s: float) -> Check:
    title = "Voice webhook demands a Twilio signature"
    cid = "twilio_callback.webhook_auth"
    try:
        reply = await fetch(
            http,
            "POST",
            f"{origin}{TWILIO_VOICE_PATH}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=b"CallSid=CA00000000000000000000000000000000&From=%2B10000000000",
            timeout_s=timeout_s,
        )
    except Unreachable as exc:
        return Check(cid, TWILIO, title, Status.BLOCKED, f"{exc.reason}.")
    if reply.status == 401:
        return Check(cid, TWILIO, title, Status.PASS, "an unsigned request was refused (401).")
    if reply.status == 404:
        return Check(
            cid,
            TWILIO,
            title,
            Status.BLOCKED,
            "404: this deployment does not serve the Twilio routes (SPARTA_TELEPHONY_PROVIDER is not twilio there) or "
            "it is not Sparta.",
            "Deploy with SPARTA_TELEPHONY_PROVIDER=twilio.",
        )
    if 200 <= reply.status < 300:
        return Check(
            cid,
            TWILIO,
            title,
            Status.BLOCKED,
            "an UNSIGNED request was accepted.",
            "Do not expose this deployment: signature verification is not active.",
        )
    return Check(
        cid,
        TWILIO,
        title,
        Status.WARNING,
        f"unexpected HTTP {reply.status} for an unsigned request.",
        "Check the deployment's logs.",
    )


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


async def _media_auth(http: httpx.AsyncClient, origin: str, timeout_s: float, *, twilio: bool = False) -> Check:
    title = "Media WebSocket demands authentication"
    group, cid = (TWILIO, "twilio_callback.media_auth") if twilio else (ACS, "callback.media_auth")
    path = TWILIO_MEDIA_PATH if twilio else MEDIA_PATH
    try:
        reply = await fetch(http, "GET", f"{origin}{path}", headers=_ws_headers(), timeout_s=timeout_s)
    except Unreachable as exc:
        return Check(cid, group, title, Status.BLOCKED, f"{exc.reason}.")
    if reply.status in (401, 403):
        return Check(
            cid,
            group,
            title,
            Status.PASS,
            f"a WebSocket upgrade without a token was refused ({reply.status}); the path reaches the API.",
        )
    if reply.status == 101:
        return Check(
            cid,
            group,
            title,
            Status.BLOCKED,
            "a WebSocket upgrade WITHOUT a token was accepted.",
            "Do not expose this deployment: the media verifier is not active.",
        )
    return Check(
        cid,
        group,
        title,
        Status.BLOCKED if reply.status in (404, 426) else Status.WARNING,
        f"the upgrade request was answered HTTP {reply.status}: the proxy may not forward WebSockets.",
        "Make sure the ingress or tunnel supports WebSockets on /api/v1/media/.",
    )


# -------------------------------------------------------------------------------------------------------- twilio
def _basic(sid: str, token: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode("ascii")}


def _same_endpoint(configured: object, expected_origin: str, path: str) -> tuple[bool, str]:
    """Whether a number's voice URL is ``expected_origin`` + ``path``; the second value names only the host (a voice
    URL can carry credentials or tokens, so it is never echoed)."""
    if not isinstance(configured, str) or not configured:
        return False, "no voice URL"
    parts = urlsplit(configured)
    expected = urlsplit(expected_origin)
    host = parts.hostname or "an unparsable host"
    same = (
        parts.scheme == "https"
        and (parts.hostname or "").lower() == (expected.hostname or "").lower()
        and (parts.port or 443) == (expected.port or 443)
        and parts.path.rstrip("/") == path
    )
    return same, host


async def twilio_online(
    settings: Settings, http: httpx.AsyncClient, timeout_s: float, override: str | None
) -> list[Check]:
    """Read-only Twilio REST calls: the account and the number's voice webhook. Free, and nothing is changed."""
    sid = settings.twilio_account_sid or ""
    secret = settings.twilio_auth_token
    if not re.fullmatch(r"AC[0-9a-f]{32}", sid) or secret is None:
        return [
            Check(
                "twilio.account",
                TWILIO,
                "Twilio account",
                Status.BLOCKED,
                "skipped: the account SID or the auth token is missing or malformed.",
                "Set SPARTA_TWILIO_ACCOUNT_SID and SPARTA_TWILIO_AUTH_TOKEN first.",
            )
        ]
    headers = _basic(sid, secret.get_secret_value())
    out = [await _twilio_account(http, sid, headers, timeout_s)]
    if out[0].status is Status.BLOCKED and "rejected" in out[0].detail:
        return out  # the credentials do not work, so asking for the numbers would only repeat the 401
    out.append(await _twilio_numbers(settings, http, sid, headers, timeout_s, override))
    return out


async def _twilio_account(http: httpx.AsyncClient, sid: str, headers: dict[str, str], timeout_s: float) -> Check:
    title = "Twilio account"
    try:
        reply = await fetch(http, "GET", f"{TWILIO_API}/Accounts/{sid}.json", headers=headers, timeout_s=timeout_s)
    except Unreachable as exc:
        return Check("twilio.account", TWILIO, title, Status.WARNING, f"{exc.reason}.", "Retry; check the network.")
    if reply.status in (401, 403):
        return Check(
            "twilio.account",
            TWILIO,
            title,
            Status.BLOCKED,
            f"the credentials were rejected (HTTP {reply.status}).",
            "Check the account SID and the auth token (the token may have been rotated).",
        )
    if reply.status == 404:
        return Check("twilio.account", TWILIO, title, Status.BLOCKED, "no such account (HTTP 404).", "Check the SID.")
    parsed = reply.json()
    if reply.status != 200 or not isinstance(parsed, dict):
        return Check(
            "twilio.account", TWILIO, title, Status.WARNING, f"unexpected HTTP {reply.status}.", "Retry later."
        )
    status, kind = str(parsed.get("status", "")), str(parsed.get("type", ""))
    if status != "active":
        return Check(
            "twilio.account",
            TWILIO,
            title,
            Status.BLOCKED,
            f"the account is {status or 'in an unknown state'}, not active.",
            "Reactivate it in the Twilio Console.",
        )
    if kind.lower() == "trial":
        return Check(
            "twilio.account",
            TWILIO,
            title,
            Status.BLOCKED,
            "a TRIAL account: Twilio removes <Stream> and <Dial><Number> from the TwiML of trial accounts, so Sparta "
            "could neither hear the caller nor hand the call to you.",
            "Upgrade the account (Twilio Console > Billing), then run this check again.",
        )
    return Check("twilio.account", TWILIO, title, Status.PASS, f"active ({kind or 'type not reported'}).")


async def _twilio_numbers(
    settings: Settings,
    http: httpx.AsyncClient,
    sid: str,
    headers: dict[str, str],
    timeout_s: float,
    override: str | None,
) -> Check:
    title = "Twilio number points at this API"
    number = settings.forwarding_number
    query = "PageSize=50" + (f"&PhoneNumber={quote(number, safe='')}" if number else "")
    try:
        reply = await fetch(
            http,
            "GET",
            f"{TWILIO_API}/Accounts/{sid}/IncomingPhoneNumbers.json?{query}",
            headers=headers,
            timeout_s=timeout_s,
        )
    except Unreachable as exc:
        return Check("twilio.number", TWILIO, title, Status.WARNING, f"{exc.reason}.", "Retry; check the network.")
    parsed = reply.json() if reply.status == 200 else None
    items = parsed.get("incoming_phone_numbers") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return Check("twilio.number", TWILIO, title, Status.WARNING, f"unexpected HTTP {reply.status}.", "Retry later.")
    entries = [item for item in items if isinstance(item, dict)]
    if not entries:
        return Check(
            "twilio.number",
            TWILIO,
            title,
            Status.BLOCKED,
            "the account has no matching phone number." if number else "the account owns no phone number.",
            "Buy or port a number in the Twilio Console, then set SPARTA_FORWARDING_NUMBER to it.",
        )
    base = https_origin(override or settings.twilio_callback_base_url)
    if base is None:
        return Check("twilio.number", TWILIO, title, Status.BLOCKED, "skipped: no valid callback URL.")
    problems: list[str] = []
    matching = 0
    for entry in entries:
        same, host = _same_endpoint(entry.get("voice_url"), base, TWILIO_VOICE_PATH)
        method = str(entry.get("voice_method", "POST")).upper()
        app = entry.get("voice_application_sid")
        label = mask_number(str(entry.get("phone_number", "")))
        if app:
            problems.append(f"{label} uses a TwiML application, which overrides its voice URL")
        elif not same:
            problems.append(f"{label} sends voice calls to {host}, not to {urlsplit(base).hostname}")
        elif method != "POST":
            problems.append(f"{label} uses HTTP {method} for voice calls; Sparta accepts POST only")
        else:
            matching += 1
    if matching == len(entries):
        return Check(
            "twilio.number",
            TWILIO,
            title,
            Status.PASS,
            f"{matching} number(s) send voice calls to {TWILIO_VOICE_PATH} over POST.",
        )
    return Check(
        "twilio.number",
        TWILIO,
        title,
        Status.BLOCKED if number or matching == 0 else Status.WARNING,
        "; ".join(problems) + ".",
        f"In the Twilio Console set the number's voice webhook to {base}{TWILIO_VOICE_PATH} (HTTP POST) and remove any "
        "TwiML application.",
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
    twilio: bool = False,
    callback_url: str | None,
    http: httpx.AsyncClient,
    timeout_s: float,
) -> list[Check]:
    """Every free network check, run concurrently. A failing probe becomes a check, never an exception."""
    jobs: list[asyncio.Future[list[Check]] | asyncio.Task[list[Check]]] = [
        asyncio.ensure_future(stores_online(settings)),
        asyncio.ensure_future(oidc_online(settings, http, timeout_s)),
    ]
    if azure or twilio:
        jobs.append(asyncio.ensure_future(speech_online(settings, http, timeout_s)))
        if settings.llm_provider == "azure_openai":
            jobs.append(asyncio.ensure_future(openai_online(settings, http, timeout_s)))
    if azure:
        jobs.append(asyncio.ensure_future(callback_online(settings, http, timeout_s, callback_url, "azure")))
    if twilio:
        jobs.append(asyncio.ensure_future(callback_online(settings, http, timeout_s, callback_url, "twilio")))
        jobs.append(asyncio.ensure_future(twilio_online(settings, http, timeout_s, callback_url)))
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
