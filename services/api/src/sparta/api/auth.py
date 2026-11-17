"""Authentication: a development identity (always shown with a banner) or OIDC bearer tokens, never both at once.

* **dev** needs no credentials and exists only for local work. ``Settings`` refuses it in production and
  ``GET /system/status`` reports ``dev_banner: true`` so every client must show it. ``X-Sparta-Dev-User`` selects another
  development identity (for isolation tests).
* **oidc** verifies ``Authorization: Bearer <JWT>`` against the issuer's signing keys (RS256 by default, asymmetric
  algorithms only, issuer and audience pinned). The dev header has no effect in this mode.

Real sign-in has not been verified against a live identity provider in this environment; the verifier is exercised with
locally generated keys in the test suite.
"""

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Protocol

import httpx
from starlette.requests import HTTPConnection

from sparta.config import ConfigurationError, Settings
from sparta.providers.azure_common import https_origin, send_bounded
from sparta.providers.base import ProviderError
from sparta.services.dto import Principal
from sparta.services.errors import ProviderUnavailableError, Unauthorized
from sparta.telephony.webhooks import (
    HttpJwksProvider,
    JwksProvider,
    JwksUnavailable,
    JwtVerifier,
    WebhookRejected,
    bearer_token,
)

log = logging.getLogger("sparta.auth")
DEV_USER = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
SAFE_SUBJECT = re.compile(r"[A-Za-z0-9_.:@\-]{1,100}")
DISCOVERY_MAX_BYTES = 65_536


class Authenticator(Protocol):
    mode: str

    async def authenticate(self, conn: HTTPConnection) -> Principal: ...


class DevAuthenticator:
    mode = "dev"

    def __init__(self, settings: Settings) -> None:
        if settings.is_production:
            raise ConfigurationError(["development authentication cannot be used in production"])
        self._default = Principal(id=settings.dev_user_id, display_name=settings.dev_user_name)

    async def authenticate(self, conn: HTTPConnection) -> Principal:
        supplied = conn.headers.get("x-sparta-dev-user")
        if supplied is None or supplied == self._default.id:
            return self._default
        if not DEV_USER.fullmatch(supplied):
            raise Unauthorized("The development user header is not valid.")
        return Principal(id=supplied, display_name=supplied)


def subject_to_user_id(subject: str) -> str:
    """The stable user id for an OIDC ``sub``: used as is when it is short and plain, hashed otherwise."""
    if SAFE_SUBJECT.fullmatch(subject):
        return subject
    return "u_" + hashlib.sha256(subject.encode()).hexdigest()[:40]


class OidcAuthenticator:
    mode = "oidc"

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        *,
        jwks: JwksProvider | None = None,
    ) -> None:
        if not settings.oidc_issuer or not settings.oidc_audience:
            raise ConfigurationError(["SPARTA_OIDC_ISSUER and SPARTA_OIDC_AUDIENCE are required for OIDC"])
        self._settings = settings
        self._http = http
        self._jwks = jwks
        self._verifier: JwtVerifier | None = None
        self._lock = asyncio.Lock()

    async def _discover_jwks_url(self) -> str:
        issuer = self._settings.oidc_issuer or ""
        base = https_origin(issuer.split("?", 1)[0])
        if base is None or self._http is None:
            raise ProviderUnavailableError("Sign-in is not configured correctly.")
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        request = self._http.build_request("GET", url, headers={"Accept": "application/json"})
        try:
            response, body = await send_bounded(
                self._http, request, provider="oidc", stage="discovery", timeout_s=5.0, cap=DISCOVERY_MAX_BYTES
            )
            document = json.loads(body) if response.status_code == 200 else None
        except (ProviderError, ValueError):
            document = None
        jwks_uri = document.get("jwks_uri") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or str(document.get("issuer", "")).rstrip("/") != issuer.rstrip("/")
            or not isinstance(jwks_uri, str)
            or https_origin(jwks_uri) is None
        ):
            raise ProviderUnavailableError("Sign-in is temporarily unavailable.")
        return jwks_uri

    async def _get_verifier(self) -> JwtVerifier:
        if self._verifier is not None:
            return self._verifier
        async with self._lock:
            if self._verifier is None:
                jwks = self._jwks
                if jwks is None:
                    if self._http is None:
                        raise ProviderUnavailableError("Sign-in is not configured correctly.")
                    url = self._settings.oidc_jwks_url or await self._discover_jwks_url()
                    jwks = HttpJwksProvider(url, self._http)
                self._verifier = JwtVerifier(
                    [self._settings.oidc_issuer or ""],
                    [self._settings.oidc_audience or ""],
                    jwks,
                    algorithms=tuple(self._settings.oidc_algorithms),
                    required_claims=("exp", "iss", "aud", "sub"),
                )
        return self._verifier

    async def authenticate(self, conn: HTTPConnection) -> Principal:
        try:
            token = bearer_token(conn.headers.get("authorization"))
        except WebhookRejected:
            raise Unauthorized("Sign in to continue.") from None
        verifier = await self._get_verifier()
        try:
            claims: dict[str, Any] = await verifier.verify(token)
        except JwksUnavailable:
            raise ProviderUnavailableError("Sign-in is temporarily unavailable.") from None
        except WebhookRejected as exc:
            log.info("access token rejected", extra={"reason": exc.reason})
            raise Unauthorized("Your session is not valid. Sign in again.") from None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise Unauthorized("Your session is not valid. Sign in again.")
        name = claims.get("name") or claims.get("preferred_username") or ""
        display = " ".join(str(name).split())[:120] if isinstance(name, str) else ""
        return Principal(id=subject_to_user_id(subject), display_name=display)


def build_authenticator(settings: Settings, http: httpx.AsyncClient | None = None) -> Authenticator:
    if settings.auth_mode == "oidc":
        return OidcAuthenticator(settings, http)
    return DevAuthenticator(settings)
