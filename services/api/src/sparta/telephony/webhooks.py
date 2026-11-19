"""Inbound webhook verification: HMAC signatures, JWT bearer tokens (ACS Call Automation, Event Grid) and parsing.

Pure utilities with no web-framework imports, so every rule is unit-testable. Failures raise :class:`WebhookRejected`
with a short static ``reason`` (never request content) and a suggested HTTP ``status_code``; nothing in this module
logs, so phone numbers and tokens cannot leak from here.

**Nothing here has been exercised against live Azure Communication Services, Event Grid or Microsoft Entra ID.**
Facts used come from ``docs/research/acs-android-verification.md``; where that file says UNVERIFIED the behaviour is
configurable and the assumption is called out next to the code.
"""

import asyncio
import hashlib
import hmac
import json
import re
import time
from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWK, PyJWTError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sparta.clock import Clock, SystemClock
from sparta.config import ConfigurationError, Settings
from sparta.providers.azure_common import send_bounded
from sparta.providers.base import ProviderError
from sparta.telephony.base import IncomingCall

PROVIDER_NAME = "azure"
MAX_TOKEN_CHARS = 16_384
EVENT_GRID_MAX_BYTES = 1_048_576
EVENT_GRID_MAX_EVENTS = 100
SUBSCRIPTION_VALIDATION_EVENT = "Microsoft.EventGrid.SubscriptionValidationEvent"
INCOMING_CALL_EVENT = "Microsoft.Communication.IncomingCall"

ACS_ISSUER = "https://acscallautomation.communication.azure.com"
ACS_JWKS_URL = f"{ACS_ISSUER}/calling/keys"
ACS_CALLBACK_MAX_LIFETIME_S = 600.0  # the documented lifetime is 5 minutes; allow double
ACS_MEDIA_MAX_LIFETIME_S = 86_400.0 + 600.0  # WebSocket connection tokens are documented as lasting 24 hours
EVENT_GRID_ROLE = "AzureEventGridSecureWebhookSubscriber"
EVENT_GRID_MAX_LIFETIME_S = 86_400.0  # Entra access tokens live at most 24 hours

_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)
_NONCE = re.compile(r"[A-Za-z0-9_\-:=+/]{8,128}")  # no '.': the signed string is f"{timestamp}.{nonce}.{body}"
_SIGNATURE = re.compile(r"(?:sha256=)?([0-9A-Fa-f]{64})")
_KID = re.compile(r"[A-Za-z0-9_\-.:=+/]{1,128}")
_TENANT_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_VALIDATION_CODE = re.compile(r"[A-Za-z0-9_\-]{1,256}")
_E164 = re.compile(r"\+?[0-9]{5,15}")
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")
_FORBIDDEN_JWT_HEADERS = frozenset({"jwk", "jku", "x5u"})  # attacker-supplied key sources: never honoured


class WebhookRejected(Exception):
    """A webhook failed verification or parsing. ``reason`` is a static, log-safe label."""

    def __init__(self, reason: str, *, status_code: int = 401) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class MalformedWebhookPayload(WebhookRejected):
    """The body is not a well-formed event batch (suggested status 400, or 413 when it is too large)."""

    def __init__(self, reason: str, *, status_code: int = 400) -> None:
        super().__init__(reason, status_code=status_code)


class JwksUnavailable(WebhookRejected):
    """The signing keys could not be fetched and no usable cached copy exists (suggested status 503)."""

    def __init__(self, reason: str = "signing keys unavailable") -> None:
        super().__init__(reason, status_code=503)


# ------------------------------------------------------------------------------------------ replay guard
@runtime_checkable
class ReplayGuard(Protocol):
    async def seen(self, key: str, ttl_s: int) -> bool:
        """True if ``key`` was already recorded and has not expired; otherwise record it and return False.

        Multi-worker deployments need a shared implementation (for example Redis ``SET key NX EX ttl``).
        """
        ...


class InMemoryReplayGuard:
    """Single-process replay guard with a bounded footprint (oldest entries are evicted first)."""

    def __init__(self, *, max_entries: int = 100_000, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._max_entries = max_entries
        self._expiry: OrderedDict[str, float] = OrderedDict()

    async def seen(self, key: str, ttl_s: int) -> bool:
        now = self._clock.monotonic()
        while self._expiry:
            oldest, oldest_expiry = next(iter(self._expiry.items()))
            if oldest_expiry > now:
                break
            del self._expiry[oldest]
        expires = self._expiry.get(key)
        if expires is not None and expires > now:
            return True
        self._expiry.pop(key, None)
        self._expiry[key] = now + ttl_s
        while len(self._expiry) > self._max_entries:
            self._expiry.popitem(last=False)
        return False


# ----------------------------------------------------------------------------------------- generic HMAC
async def verify_generic_hmac(
    secret: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    signature_hex: str,
    *,
    now: float,
    tolerance_s: int = 300,
    replay: ReplayGuard,
) -> None:
    """Verify ``HMAC-SHA256(secret, f"{timestamp}.{nonce}." + body)`` for a provider-neutral webhook.

    ``timestamp`` is integer Unix seconds. The nonce may not contain ``.`` so the signed string is unambiguous (a
    signature for one ``(nonce, body)`` split can never validate another). The nonce is recorded only *after* the
    signature verified, so unauthenticated senders cannot poison the replay cache.
    """
    if not secret:
        raise WebhookRejected("webhook secret not configured")
    if not (timestamp.isascii() and timestamp.isdigit() and len(timestamp) <= 12):
        raise WebhookRejected("invalid timestamp")
    if abs(now - int(timestamp)) > tolerance_s:
        raise WebhookRejected("stale timestamp")
    if not _NONCE.fullmatch(nonce):
        raise WebhookRejected("invalid nonce")
    match = _SIGNATURE.fullmatch(signature_hex.strip())
    if match is None:
        raise WebhookRejected("invalid signature")
    expected = hmac.new(secret.encode("utf-8"), f"{timestamp}.{nonce}.".encode() + body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, bytes.fromhex(match.group(1))):
        raise WebhookRejected("invalid signature")
    if await replay.seen(f"hmac:{nonce}", 2 * tolerance_s + 1):
        raise WebhookRejected("replayed request")


def bearer_token(authorization: str | None) -> str:
    """The token from an ``Authorization: Bearer <token>`` header value."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        raise WebhookRejected("missing bearer token")
    return token


# ----------------------------------------------------------------------------------------------- JWKS
@runtime_checkable
class JwksProvider(Protocol):
    async def get_key(self, kid: str) -> PyJWK:
        """The verification key for ``kid``; raises :class:`WebhookRejected` when it is not a trusted key."""
        ...


class HttpJwksProvider:
    """Fetches a JWKS from ONE configured https URL and caches it.

    * Keys are trusted only if they came from ``url``: redirects are not followed and token headers (``jku``, ``jwk``,
      ``x5u``) are never consulted.
    * An unknown ``kid`` triggers at most one refetch per ``min_refetch_s``, so random key ids cannot make this a
      request amplifier; a stale cache is used for up to ``stale_if_error_s`` when the endpoint is unreachable.
    * Only RSA signing keys of at least 2048 bits are loaded.
    """

    def __init__(
        self,
        url: str,
        http: httpx.AsyncClient,
        ttl_s: float = 3600.0,
        min_refetch_s: float = 30.0,
        *,
        stale_if_error_s: float = 86_400.0,
        timeout_s: float = 5.0,
        max_bytes: int = 262_144,
        clock: Clock | None = None,
    ) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError("the JWKS URL must be a plain https URL")
        self._url = url
        self._http = http
        self._ttl_s = ttl_s
        self._min_refetch_s = min_refetch_s
        self._stale_if_error_s = stale_if_error_s
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._clock = clock or SystemClock()
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> PyJWK:
        async with self._lock:
            now = self._clock.monotonic()
            may_fetch = self._last_attempt is None or now - self._last_attempt >= self._min_refetch_s
            fresh = self._fetched_at is not None and now - self._fetched_at < self._ttl_s
            if may_fetch and (not fresh or kid not in self._keys):
                await self._refresh(now)
            usable = self._fetched_at is not None and now - self._fetched_at < self._ttl_s + self._stale_if_error_s
            if not usable:
                raise JwksUnavailable
            key = self._keys.get(kid)
        if key is None:
            raise WebhookRejected("unknown signing key")
        return key

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now
        try:
            keys = await self._fetch()
        except (ProviderError, ValueError, TypeError, RecursionError, OSError):
            return  # keep serving the previous key set (if it is not too stale); the next attempt is rate limited
        self._keys, self._fetched_at = keys, now

    async def _fetch(self) -> dict[str, PyJWK]:
        request = self._http.build_request(
            "GET", self._url, headers={"Accept": "application/json"}, timeout=self._timeout_s
        )
        response, body = await send_bounded(
            self._http, request, provider="jwks", stage="fetch", timeout_s=self._timeout_s, cap=self._max_bytes
        )
        if response.status_code != 200:
            raise ValueError("unexpected status")
        document = json.loads(body)
        entries = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise ValueError("no key list")
        keys: dict[str, PyJWK] = {}
        for entry in entries:
            loaded = _load_signing_key(entry)
            if loaded is not None:
                keys[loaded[0]] = loaded[1]
        if not keys:
            raise ValueError("no usable keys")
        return keys


def _load_signing_key(entry: object) -> tuple[str, PyJWK] | None:
    if not isinstance(entry, dict) or entry.get("kty") != "RSA" or entry.get("use") not in (None, "sig"):
        return None
    kid = entry.get("kid")
    if not isinstance(kid, str) or not _KID.fullmatch(kid):
        return None
    try:
        # The advertised "alg" is dropped on purpose: ACS's discovery document says "RSA256" (UNVERIFIED which spelling
        # the keys use), and tokens are checked against the verifier's own allow-list instead.
        jwk = PyJWK({k: v for k, v in entry.items() if k != "alg"})
        if int(jwk.key.key_size) < 2048:
            return None
    except (PyJWTError, ValueError, TypeError, AttributeError):
        return None
    return kid, jwk


# ----------------------------------------------------------------------------------------------- JWT
class JwtVerifier:
    """Strict bearer-token verification with PyJWT. Never decodes an unverified payload.

    Rejects: ``alg=none``, symmetric algorithms and algorithm confusion (the allow-list is explicit and asymmetric
    only), a missing or unknown ``kid``, tokens naming their own key (``jwk``/``jku``/``x5u``), wrong issuer or
    audience, expired or not-yet-valid tokens, missing required claims, a missing required role, and (when
    ``max_lifetime_s`` is set) tokens valid for longer than that.
    """

    def __init__(
        self,
        issuers: Sequence[str],
        audiences: Sequence[str],
        jwks: JwksProvider,
        algorithms: Sequence[str] = ("RS256",),
        leeway_s: float = 30,
        max_lifetime_s: float | None = None,
        required_claims: Sequence[str] = ("exp", "iss", "aud"),
        required_role: str | None = None,
        allowed_app_ids: Sequence[str] = (),
    ) -> None:
        if not issuers or not audiences or not all(issuers) or not all(audiences):
            raise ValueError("issuers and audiences must be non-empty")
        if not algorithms or not set(algorithms) <= _ASYMMETRIC_ALGORITHMS:
            raise ValueError("only asymmetric signature algorithms are allowed")
        self._issuers = list(issuers)
        self._audiences = list(audiences)
        self._jwks = jwks
        self._algorithms = list(algorithms)
        self._leeway_s = leeway_s
        self._max_lifetime_s = max_lifetime_s
        self._required = sorted({"exp", "iss", "aud", *required_claims})
        self._required_role = required_role
        self._allowed_app_ids = frozenset(app_id.lower() for app_id in allowed_app_ids)

    async def verify(self, token: str) -> dict[str, Any]:
        if not token or len(token) > MAX_TOKEN_CHARS:
            raise WebhookRejected("malformed token")
        try:
            header = jwt.get_unverified_header(token)  # the header only: it is needed to pick the key
        except PyJWTError:
            raise WebhookRejected("malformed token") from None
        if header.get("alg") not in self._algorithms:
            raise WebhookRejected("unsupported algorithm")
        if _FORBIDDEN_JWT_HEADERS & header.keys():
            raise WebhookRejected("unsupported key reference")
        kid = header.get("kid")
        if not isinstance(kid, str) or not _KID.fullmatch(kid):
            raise WebhookRejected("missing key id")
        key = await self._jwks.get_key(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=self._algorithms,
                audience=self._audiences,
                issuer=self._issuers,
                leeway=self._leeway_s,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "require": self._required,
                },
            )
        except jwt.ExpiredSignatureError:
            raise WebhookRejected("token expired") from None
        except jwt.ImmatureSignatureError:
            raise WebhookRejected("token not yet valid") from None
        except jwt.InvalidAudienceError:
            raise WebhookRejected("invalid audience") from None
        except jwt.InvalidIssuerError:
            raise WebhookRejected("invalid issuer") from None
        except jwt.MissingRequiredClaimError:
            raise WebhookRejected("missing claim") from None
        except jwt.InvalidSignatureError:
            raise WebhookRejected("invalid signature") from None
        except PyJWTError:
            raise WebhookRejected("invalid token") from None
        self._check_lifetime(claims)
        self._check_role(claims)
        self._check_caller(claims)
        return claims

    def _check_lifetime(self, claims: dict[str, Any]) -> None:
        if self._max_lifetime_s is None:
            return
        issued = next((claims[c] for c in ("iat", "nbf") if isinstance(claims.get(c), int | float)), time.time())
        if float(claims["exp"]) - float(issued) > self._max_lifetime_s + self._leeway_s:
            raise WebhookRejected("token lifetime too long")

    def _check_role(self, claims: dict[str, Any]) -> None:
        if self._required_role is None:
            return
        roles = claims.get("roles")
        if not isinstance(roles, list) or self._required_role not in roles:
            raise WebhookRejected("missing required role")

    def _check_caller(self, claims: dict[str, Any]) -> None:
        """The calling application: ``azp`` in v2 tokens, ``appid`` in v1. The Event Grid role is also granted to the
        subscription-writer app, so the role alone does not show that Event Grid is the caller."""
        if not self._allowed_app_ids:
            return
        callers = {str(claims[name]).lower() for name in ("azp", "appid") if claims.get(name) is not None}
        if not callers or not callers <= self._allowed_app_ids:
            raise WebhookRejected("caller application not allowed")


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def acs_callback_verifier(
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    max_lifetime_s: float | None = ACS_CALLBACK_MAX_LIFETIME_S,
    clock: Clock | None = None,
) -> JwtVerifier:
    """Verifier for ACS Call Automation callbacks (and, with ``max_lifetime_s=ACS_MEDIA_MAX_LIFETIME_S``, the media
    WebSocket upgrade).

    Issuer, JWKS URL, RS256 and the audience being the ACS resource id come from the research notes. UNVERIFIED: the
    exact audience representation (``SPARTA_ACS_RESOURCE_ID`` may list several, comma separated) and the algorithm
    name: ACS's discovery document advertises ``RSA256`` while its sample says ``RS256``. Only ``RS256`` is accepted
    here (``RSA256`` is not a registered JWS algorithm); if an integration test shows ``RSA256`` in real token
    headers, register an alias before enabling live calls.
    """
    audiences = _csv(settings.acs_resource_id)
    if not audiences:
        raise ConfigurationError(
            ["SPARTA_ACS_RESOURCE_ID is required to verify Azure Communication Services callbacks"]
        )
    jwks = HttpJwksProvider(ACS_JWKS_URL, http, clock=clock)
    return JwtVerifier([ACS_ISSUER], audiences, jwks, algorithms=("RS256",), max_lifetime_s=max_lifetime_s)


def event_grid_verifier(
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    required_role: str | None = EVENT_GRID_ROLE,
    clock: Clock | None = None,
) -> JwtVerifier:
    """Verifier for Event Grid secure-webhook (Microsoft Entra) bearer tokens.

    Issuer ``https://login.microsoftonline.com/{tenant}/v2.0`` (the v1 issuer ``https://sts.windows.net/{tenant}/`` is
    also accepted, because an app registration issues v1 tokens unless ``accessTokenAcceptedVersion`` is 2) and the
    v2 JWKS from the research notes. UNVERIFIED: that live deliveries carry the ``AzureEventGridSecureWebhookSubscriber``
    role in ``roles`` (pass ``required_role=None`` to disable that check) and which audience form (application id or
    URI) the app uses (``SPARTA_EVENT_GRID_AUDIENCE`` may list several, comma separated).
    """
    tenant = (settings.entra_tenant_id or "").strip()
    audiences = _csv(settings.event_grid_audience)
    app_ids = _csv(settings.event_grid_allowed_app_ids)
    problems: list[str] = []
    if not _TENANT_GUID.fullmatch(tenant):
        problems.append("SPARTA_ENTRA_TENANT_ID must be the tenant GUID to verify Event Grid deliveries")
    if not audiences:
        problems.append("SPARTA_EVENT_GRID_AUDIENCE is required to verify Event Grid deliveries")
    if not all(_TENANT_GUID.fullmatch(app_id) for app_id in app_ids):
        problems.append("SPARTA_EVENT_GRID_ALLOWED_APP_IDS must list application (client) id GUIDs")
    if problems:
        raise ConfigurationError(problems)
    jwks = HttpJwksProvider(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", http, clock=clock)
    issuers = [f"https://login.microsoftonline.com/{tenant}/v2.0", f"https://sts.windows.net/{tenant}/"]
    return JwtVerifier(
        issuers,
        audiences,
        jwks,
        algorithms=("RS256",),
        max_lifetime_s=EVENT_GRID_MAX_LIFETIME_S,
        required_role=required_role,
        allowed_app_ids=app_ids,
    )


# ------------------------------------------------------------------------------------------ Event Grid
class EventGridEvent(BaseModel):
    """One Event Grid-schema event (camelCase field names are the wire names). Unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=256)
    topic: str | None = Field(default=None, max_length=1024)
    subject: str = Field(default="", max_length=1024)
    eventType: str = Field(min_length=1, max_length=256)
    eventTime: str | None = Field(default=None, max_length=64)
    dataVersion: str | None = Field(default=None, max_length=32)
    data: dict[str, Any] = Field(default_factory=dict)


def parse_event_grid(
    body: bytes, *, max_bytes: int = EVENT_GRID_MAX_BYTES, max_events: int = EVENT_GRID_MAX_EVENTS
) -> list[EventGridEvent]:
    """Parse an Event Grid-schema delivery (a JSON array of events) with strict size limits.

    Only the Event Grid schema is supported, not CloudEvents: create the subscription with
    ``--event-delivery-schema eventgridschema``.
    """
    if len(body) > max_bytes:
        raise MalformedWebhookPayload("payload too large", status_code=413)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        raise MalformedWebhookPayload("invalid JSON") from None
    if not isinstance(payload, list) or not payload or len(payload) > max_events:
        raise MalformedWebhookPayload("expected a non-empty event array")
    events: list[EventGridEvent] = []
    for item in payload:
        try:
            events.append(EventGridEvent.model_validate(item))
        except ValidationError:
            raise MalformedWebhookPayload("invalid event") from None
    return events


def subscription_validation_response(events: Sequence[EventGridEvent]) -> dict[str, str] | None:
    """``{"validationResponse": code}`` for a subscription-validation handshake, else ``None``.

    The handshake does not authenticate later deliveries: verify the bearer token of every request first.
    """
    for event in events:
        if event.eventType == SUBSCRIPTION_VALIDATION_EVENT:
            code = event.data.get("validationCode")
            if not isinstance(code, str) or not _VALIDATION_CODE.fullmatch(code):
                raise MalformedWebhookPayload("invalid validation code")
            return {"validationResponse": code}
    return None


def _text(value: object, limit: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _phone_number(identifier: object) -> str | None:
    """E.164 digits from an ACS communication identifier (``phoneNumber.value``, else ``rawId`` ``4:+<number>``)."""
    if not isinstance(identifier, dict):
        return None
    phone = identifier.get("phoneNumber")
    value = phone.get("value") if isinstance(phone, dict) else None
    if not isinstance(value, str):
        raw = identifier.get("rawId")
        value = raw[2:] if isinstance(raw, str) and raw.startswith("4:") else None
    return value if isinstance(value, str) and _E164.fullmatch(value) else None


def incoming_call_from_event(event: EventGridEvent, now: datetime) -> IncomingCall:
    """Map a ``Microsoft.Communication.IncomingCall`` event to an :class:`IncomingCall` (numbers are never logged)."""
    if event.eventType != INCOMING_CALL_EVENT:
        raise MalformedWebhookPayload("not an incoming call event")
    data = event.data
    context = _text(data.get("incomingCallContext"), 8192)
    server_call_id = _text(data.get("serverCallId"), 512)
    if context is None or server_call_id is None:
        raise MalformedWebhookPayload("incoming call event is incomplete")
    display = data.get("callerDisplayName")
    cleaned = " ".join(_CONTROL.sub(" ", display).split())[:64] if isinstance(display, str) else ""
    return IncomingCall(
        provider=PROVIDER_NAME,
        provider_call_id=server_call_id,
        caller_number=_phone_number(data.get("from")),
        called_number=_phone_number(data.get("to")),
        display_name=cleaned or None,
        correlation_id=_text(data.get("correlationId"), 128),
        received_at=now,
        context=context,
    )
