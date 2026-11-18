"""Locally generated signing keys and tokens for authentication tests (no network, no real identity provider)."""

import base64
import hashlib
import hmac
import json
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from sparta.telephony.webhooks import WebhookRejected

KID = "test-key-1"


class StaticJwks:
    """A JWKS with one known key."""

    def __init__(self, public_key: rsa.RSAPublicKey, kid: str = KID) -> None:
        jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
        jwk.update(kid=kid, use="sig")
        self._key = PyJWK(jwk)
        self._kid = kid

    async def get_key(self, kid: str) -> PyJWK:
        if kid != self._kid:
            raise WebhookRejected("unknown signing key")
        return self._key


class Idp:
    """An identity provider stand-in: one RSA key pair, tokens with sensible defaults and the classic attack tokens."""

    def __init__(self, issuer: str, audience: str) -> None:
        self.issuer, self.audience = issuer, audience
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = self.private.public_key()
        self.public_pem = self.public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def jwks(self) -> StaticJwks:
        return StaticJwks(self.public)

    def token(self, **overrides: object) -> str:
        now = int(time.time())
        claims: dict[str, object] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": "user-a",
            "name": "Alice A",
            "iat": now,
            "nbf": now - 5,
            "exp": now + 3600,
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": KID})

    def hs256_confusion_token(self) -> str:
        """HS256 signed with the *public* key as the HMAC secret (algorithm confusion)."""

        def b64(raw: bytes) -> bytes:
            return base64.urlsafe_b64encode(raw).rstrip(b"=")

        now = int(time.time())
        header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        payload = b64(
            json.dumps({"iss": self.issuer, "aud": self.audience, "sub": "attacker", "exp": now + 3600}).encode()
        )
        signing_input = header + b"." + payload
        signature = b64(hmac.new(self.public_pem, signing_input, hashlib.sha256).digest())
        return (signing_input + b"." + signature).decode()

    def unsigned_token(self) -> str:
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": self.audience, "sub": "attacker", "exp": now + 3600}
        return jwt.encode(claims, key=None, algorithm="none", headers={"kid": KID})
