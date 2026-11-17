"""Webhook verification: generic HMAC, JWKS caching, strict JWT verification, Event Grid parsing and mapping."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
import pytest

from sparta.clock import VirtualClock
from sparta.config import ConfigurationError
from sparta.telephony import webhooks
from sparta.telephony.base import IncomingCall
from sparta.telephony.webhooks import (
    ACS_ISSUER,
    ACS_JWKS_URL,
    ACS_MEDIA_MAX_LIFETIME_S,
    EVENT_GRID_ROLE,
    EventGridEvent,
    HttpJwksProvider,
    InMemoryReplayGuard,
    JwksProvider,
    JwksUnavailable,
    JwtVerifier,
    MalformedWebhookPayload,
    ReplayGuard,
    WebhookRejected,
    acs_callback_verifier,
    bearer_token,
    event_grid_verifier,
    incoming_call_from_event,
    parse_event_grid,
    subscription_validation_response,
    verify_generic_hmac,
)

from .conftest import ACS_RESOURCE, EVENT_GRID_AUDIENCE, TENANT
from .helpers import MockHttp, StaticJwks, b64, claims, hs256_token, jwks_response, unsigned_token

SECRET = "whsec-test-secret"
NOW = 1_800_000_000.0
BODY = b'{"event":"incoming","n":1}'
ISS, AUD = "https://issuer.example", "api://sparta"
JWKS_URL = "https://issuer.example/keys"


def sign(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()


async def check_hmac(guard=None, **overrides):
    values = {
        "secret": SECRET,
        "timestamp": str(int(NOW)),
        "nonce": "nonce-0001-abcd",
        "body": BODY,
        "signature_hex": None,
        "now": NOW,
        "tolerance_s": 300,
        "replay": guard or InMemoryReplayGuard(),
    }
    values.update(overrides)
    if values["signature_hex"] is None:
        values["signature_hex"] = sign(SECRET, values["timestamp"], values["nonce"], values["body"])
    return await verify_generic_hmac(
        values["secret"],
        values["timestamp"],
        values["nonce"],
        values["body"],
        values["signature_hex"],
        now=values["now"],
        tolerance_s=values["tolerance_s"],
        replay=values["replay"],
    )


async def reason_of(coro) -> str:
    with pytest.raises(WebhookRejected) as err:
        await coro
    return err.value.reason


# ----------------------------------------------------------------------------------------- HMAC
async def test_a_correctly_signed_fresh_request_is_accepted():
    assert await check_hmac() is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"secret": "wrong-secret"},
        {"body": b'{"event":"incoming","n":2}'},
        {"timestamp": str(int(NOW) + 1)},
        {"nonce": "nonce-0002-abcd"},
        {"signature_hex": "0" * 64},
        {"signature_hex": "zz" * 32},
        {"signature_hex": "ab" * 31},
        {"signature_hex": ""},
    ],
)
async def test_a_bad_signature_is_rejected(overrides):
    valid = sign(SECRET, str(int(NOW)), "nonce-0001-abcd", BODY)
    if "secret" in overrides or "body" in overrides or "timestamp" in overrides or "nonce" in overrides:
        overrides = {**overrides, "signature_hex": valid}  # the signature of the ORIGINAL message
    assert await reason_of(check_hmac(**overrides)) == "invalid signature"


async def test_signature_formats_are_normalised_but_nothing_else_is_accepted():
    valid = sign(SECRET, str(int(NOW)), "nonce-0001-abcd", BODY)
    assert await check_hmac(signature_hex=valid.upper()) is None
    assert await check_hmac(signature_hex=f"sha256={valid}", guard=InMemoryReplayGuard()) is None
    assert await check_hmac(signature_hex=f"  {valid}\n", guard=InMemoryReplayGuard()) is None
    assert await reason_of(check_hmac(signature_hex=f"sha1={valid}")) == "invalid signature"


@pytest.mark.parametrize("delta", [-301, 301, -86_400, 86_400, 10**9])
async def test_a_stale_or_future_timestamp_is_rejected(delta):
    assert await reason_of(check_hmac(timestamp=str(int(NOW) + delta))) == "stale timestamp"


@pytest.mark.parametrize("delta", [-300, 300, 0, 299])
async def test_the_tolerance_window_is_inclusive(delta):
    assert await check_hmac(timestamp=str(int(NOW) + delta)) is None


@pytest.mark.parametrize(
    "timestamp", ["", "abc", "17e9", "1800000000.5", "-1800000000", "\u0661\u0662\u0663", "9" * 13]
)
async def test_a_malformed_timestamp_is_rejected(timestamp):
    assert await reason_of(check_hmac(timestamp=timestamp, signature_hex="0" * 64)) == "invalid timestamp"


@pytest.mark.parametrize(
    "nonce", ["", "short", "has.dot-in-it", "white space nonce", "x" * 129, "bad\nnonce-123", "ünïcödé-nonce"]
)
async def test_a_malformed_nonce_is_rejected(nonce):
    assert await reason_of(check_hmac(nonce=nonce, signature_hex="0" * 64)) == "invalid nonce"


async def test_the_signed_string_is_unambiguous_so_a_nonce_body_split_cannot_be_replayed():
    guard = InMemoryReplayGuard()
    ts = str(int(NOW))
    # The signature for (nonce="aaaaaaaa", body="bbbb.cccc") is also the signature of "ts.aaaaaaaa.bbbb.cccc".
    signature = sign(SECRET, ts, "aaaaaaaa", b"bbbb.cccc")
    assert await check_hmac(guard, nonce="aaaaaaaa", body=b"bbbb.cccc", signature_hex=signature) is None
    # Re-splitting the same bytes as (nonce="aaaaaaaa.bbbb", body="cccc") would dodge the replay key: it is refused.
    assert (
        await reason_of(check_hmac(guard, nonce="aaaaaaaa.bbbb", body=b"cccc", signature_hex=signature))
        == "invalid nonce"
    )


async def test_a_replayed_request_is_rejected_but_a_new_nonce_is_fine():
    guard = InMemoryReplayGuard()
    assert await check_hmac(guard) is None
    assert await reason_of(check_hmac(guard)) == "replayed request"
    assert await check_hmac(guard, nonce="nonce-0002-abcd") is None


async def test_a_forged_request_cannot_poison_the_replay_cache():
    guard = InMemoryReplayGuard()
    assert await reason_of(check_hmac(guard, signature_hex="0" * 64)) == "invalid signature"
    assert await check_hmac(guard) is None  # the legitimate sender with the same nonce still gets through


async def test_an_unconfigured_secret_fails_closed():
    assert await reason_of(check_hmac(secret="", signature_hex="0" * 64)) == "webhook secret not configured"


async def test_signatures_are_compared_in_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr(webhooks.hmac, "compare_digest", spy)
    await check_hmac()
    assert calls == [(32, 32)]


async def test_the_replay_ttl_covers_the_whole_acceptance_window():
    seen: list[tuple[str, int]] = []

    class Guard:
        async def seen(self, key: str, ttl_s: int) -> bool:
            seen.append((key, ttl_s))
            return False

    assert isinstance(Guard(), ReplayGuard)
    await check_hmac(Guard(), tolerance_s=120)
    assert seen == [("hmac:nonce-0001-abcd", 241)]


async def test_the_in_memory_guard_expires_entries_and_stays_bounded():
    clock = VirtualClock()
    guard = InMemoryReplayGuard(max_entries=3, clock=clock)
    assert await guard.seen("a", 10) is False and await guard.seen("a", 10) is True
    await clock.advance(9.9)
    assert await guard.seen("a", 10) is True
    await clock.advance(0.2)
    assert await guard.seen("a", 10) is False  # expired, recorded again
    for key in "bcde":
        await guard.seen(key, 100)
    assert len(guard._expiry) == 3 and await guard.seen("b", 100) is False  # the oldest was evicted


def test_bearer_token_extraction():
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi" and bearer_token("bearer   x.y.z ") == "x.y.z"
    for bad in (None, "", "Bearer", "Bearer ", "Basic abc", "Bearer a b", "abc"):
        with pytest.raises(WebhookRejected, match="missing bearer token"):
            bearer_token(bad)


# ------------------------------------------------------------------------------------------- JWT
def verifier(jwks, **kw) -> JwtVerifier:
    return JwtVerifier(kw.pop("issuers", [ISS]), kw.pop("audiences", [AUD]), jwks, **kw)


async def test_a_valid_token_returns_its_claims(key):
    jwks = StaticJwks(key)
    result = await verifier(jwks).verify(key.token(claims(ISS, AUD, sub="owner-1")))
    assert result["sub"] == "owner-1" and result["iss"] == ISS and jwks.asked == ["key-1"]
    assert isinstance(jwks, JwksProvider)


async def test_a_signature_from_a_different_key_with_the_same_kid_is_rejected(key, other_key):
    token = other_key.token(claims(ISS, AUD))
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == "invalid signature"


async def test_a_tampered_payload_is_rejected(key):
    header, _payload, signature = key.token(claims(ISS, AUD, sub="a")).split(".")
    forged = b64(json.dumps({"iss": ISS, "aud": AUD, "exp": 4_000_000_000, "sub": "admin"}).encode())
    assert await reason_of(verifier(StaticJwks(key)).verify(f"{header}.{forged}.{signature}")) == "invalid signature"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://evil.example"}, "invalid issuer"),
        ({"iss": ISS + "/"}, "invalid issuer"),
        ({"aud": "api://someone-else"}, "invalid audience"),
        ({"aud": ["api://a", "api://b"]}, "invalid audience"),
        ({"exp": "soon"}, "invalid token"),
    ],
)
async def test_wrong_issuer_audience_or_claim_types_are_rejected(key, overrides, reason):
    token = key.token(claims(ISS, AUD, **overrides))
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == reason


async def test_audience_lists_and_multiple_accepted_audiences_work(key):
    v = verifier(StaticJwks(key), audiences=[AUD, "api://second"])
    assert (await v.verify(key.token(claims(ISS, ["x", "api://second"]))))["iss"] == ISS
    assert (await v.verify(key.token(claims(ISS, AUD))))["aud"] == AUD
    assert await reason_of(v.verify(key.token(claims(ISS, ["x", "y"])))) == "invalid audience"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": -60}, "token expired"),
        ({"exp": -3600}, "token expired"),
        ({"nbf": 120}, "token not yet valid"),
        ({"iat": 120, "nbf": None}, "token not yet valid"),
    ],
)
async def test_time_bounds_are_enforced_with_a_small_leeway(key, overrides, reason):
    import time

    now = int(time.time())
    adjusted = {k: (None if v is None else now + v) for k, v in overrides.items()}
    token = key.token(claims(ISS, AUD, **adjusted))
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == reason


async def test_clock_skew_within_the_leeway_is_tolerated(key):
    import time

    now = int(time.time())
    skewed = key.token(claims(ISS, AUD, exp=now - 10, nbf=now + 10, iat=now + 10))
    assert (await verifier(StaticJwks(key), leeway_s=30).verify(skewed))["iss"] == ISS
    assert await reason_of(verifier(StaticJwks(key), leeway_s=0).verify(skewed)) in {
        "token expired",
        "token not yet valid",
    }


async def test_algorithm_none_is_rejected_before_any_key_lookup(key):
    jwks = StaticJwks(key)
    for kid in ("key-1", None):
        assert await reason_of(verifier(jwks).verify(unsigned_token(claims(ISS, AUD), kid))) == "unsupported algorithm"
    assert jwks.asked == []


async def test_hs256_algorithm_confusion_with_the_public_key_as_secret_is_rejected(key):
    jwks = StaticJwks(key)
    for secret in (key.public_pem(), b"a-random-shared-secret-of-sufficient-length-xx"):
        token = hs256_token(secret, claims(ISS, AUD), "key-1")
        assert await reason_of(verifier(jwks).verify(token)) == "unsupported algorithm"
    assert jwks.asked == []  # rejected on the header alone: the key was never even fetched


async def test_an_rs256_header_with_an_hmac_signature_is_rejected(key):
    header, payload, _ = key.token(claims(ISS, AUD)).split(".")
    import base64

    fake = base64.urlsafe_b64encode(hmac.new(key.public_pem(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    token = f"{header}.{payload}.{fake.rstrip(b'=').decode()}"
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == "invalid signature"


async def test_a_missing_or_malformed_kid_is_rejected_without_a_lookup(key):
    jwks = StaticJwks(key)
    assert await reason_of(verifier(jwks).verify(key.token(claims(ISS, AUD), kid=None))) == "missing key id"
    for bad in ("x" * 200, "has space", "a\nb", "k\u00e9y", "<script>"):
        assert await reason_of(verifier(jwks).verify(key.token(claims(ISS, AUD), kid=bad))) == "missing key id"
    assert jwks.asked == []


async def test_a_non_string_kid_is_a_malformed_token(key):
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": 123}).encode())
    token = f"{header}.{b64(json.dumps(claims(ISS, AUD)).encode())}.{b64(b'signature')}"
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == "malformed token"


async def test_an_unknown_kid_is_rejected(key):
    token = key.token(claims(ISS, AUD), kid="not-published")
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == "unknown signing key"


@pytest.mark.parametrize(
    "header", [{"jku": "https://evil.example/jwks"}, {"jwk": {"kty": "RSA"}}, {"x5u": "https://evil.example/c"}]
)
async def test_tokens_that_name_their_own_key_source_are_rejected(key, header):
    jwks = StaticJwks(key)
    assert (
        await reason_of(verifier(jwks).verify(key.token(claims(ISS, AUD), headers=header)))
        == "unsupported key reference"
    )
    assert jwks.asked == []


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c", "...", "x" * 20_000])
async def test_garbage_is_a_malformed_token(key, token):
    assert await reason_of(verifier(StaticJwks(key)).verify(token)) == "malformed token"


async def test_a_well_formed_token_without_a_key_id_is_a_missing_key_id(key):
    assert await reason_of(verifier(StaticJwks(key)).verify("eyJhbGciOiJSUzI1NiJ9.e30.")) == "missing key id"


@pytest.mark.parametrize("missing", ["exp", "iss", "aud"])
async def test_the_core_claims_are_always_required(key, missing):
    token = key.token(claims(ISS, AUD, **{missing: None}))
    assert await reason_of(verifier(StaticJwks(key), required_claims=()).verify(token)) == "missing claim"


async def test_extra_required_claims_are_enforced(key):
    v = verifier(StaticJwks(key), required_claims=("exp", "sub", "iat"))
    assert await reason_of(v.verify(key.token(claims(ISS, AUD, sub=None)))) == "missing claim"
    assert (await v.verify(key.token(claims(ISS, AUD))))["sub"] == "subject"


@pytest.mark.parametrize(
    ("exp_in", "iat_ago", "ok"),
    [
        (300, 0, True),
        (600, 0, True),
        (629, 0, True),
        (700, 0, False),
        (3600, 0, False),
        (60, 3000, False),
        (30, 500, True),
    ],
)
async def test_tokens_valid_for_too_long_are_rejected(key, exp_in, iat_ago, ok):
    import time

    now = int(time.time())
    token = key.token(claims(ISS, AUD, iat=now - iat_ago, nbf=None, exp=now + exp_in))
    v = verifier(StaticJwks(key), max_lifetime_s=600, leeway_s=30)
    if ok:
        assert (await v.verify(token))["iss"] == ISS
    else:
        assert await reason_of(v.verify(token)) == "token lifetime too long"


async def test_without_an_issue_time_the_remaining_validity_is_bounded(key):
    import time

    now = int(time.time())
    v = verifier(StaticJwks(key), max_lifetime_s=600)
    assert (
        await reason_of(v.verify(key.token(claims(ISS, AUD, iat=None, nbf=None, exp=now + 3600))))
        == "token lifetime too long"
    )
    assert (await v.verify(key.token(claims(ISS, AUD, iat=None, nbf=None, exp=now + 300))))["iss"] == ISS
    assert (await verifier(StaticJwks(key)).verify(key.token(claims(ISS, AUD, exp=now + 86_400))))["iss"] == ISS


async def test_the_required_role_must_be_present_as_a_list_entry(key):
    v = verifier(StaticJwks(key), required_role="Subscriber")
    assert (await v.verify(key.token(claims(ISS, AUD, roles=["x", "Subscriber"]))))["roles"] == ["x", "Subscriber"]
    for roles in (None, [], ["Other"], "Subscriber", {"Subscriber": True}):
        assert await reason_of(v.verify(key.token(claims(ISS, AUD, roles=roles)))) == "missing required role"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"algorithms": ("HS256",)},
        {"algorithms": ("RS256", "none")},
        {"algorithms": ("HS512", "RS256")},
        {"algorithms": ()},
        {"issuers": []},
        {"issuers": [""]},
        {"audiences": []},
    ],
)
def test_unsafe_verifier_configurations_are_refused(key, kwargs):
    with pytest.raises(ValueError):
        verifier(StaticJwks(key), **kwargs)


# ------------------------------------------------------------------------------------------ JWKS
def jwks_provider(http, clock=None, **kw) -> HttpJwksProvider:
    return HttpJwksProvider(JWKS_URL, http.client, clock=clock or VirtualClock(), **kw)


async def test_the_jwks_is_fetched_once_and_cached(key):
    http = MockHttp(jwks_response(key))
    provider = jwks_provider(http)
    first, second = await provider.get_key("key-1"), await provider.get_key("key-1")
    assert first is second and len(http.requests) == 1
    request = http.requests[0]
    assert request.method == "GET" and str(request.url) == JWKS_URL
    assert request.headers["accept"] == "application/json" and "authorization" not in request.headers
    assert isinstance(provider, JwksProvider)


async def test_the_cache_expires_after_the_ttl(key):
    clock, http = VirtualClock(), MockHttp(jwks_response(key))
    provider = jwks_provider(http, clock, ttl_s=100)
    await provider.get_key("key-1")
    await clock.advance(99)
    await provider.get_key("key-1")
    assert len(http.requests) == 1
    await clock.advance(2)
    await provider.get_key("key-1")
    assert len(http.requests) == 2


async def test_an_unknown_kid_refetches_once_and_is_rate_limited(key):
    clock, http = VirtualClock(), MockHttp(jwks_response(key))
    provider = jwks_provider(http, clock, min_refetch_s=30)
    await provider.get_key("key-1")
    await clock.advance(31)
    for _ in range(5):
        with pytest.raises(WebhookRejected, match="unknown signing key"):
            await provider.get_key("random-kid")
    assert len(http.requests) == 2  # one refetch for the unknown kid, then the rate limit held
    await clock.advance(31)
    with pytest.raises(WebhookRejected, match="unknown signing key"):
        await provider.get_key("random-kid")
    assert len(http.requests) == 3


async def test_a_rotated_key_is_picked_up_by_the_unknown_kid_refetch(key, rotated_key):
    clock, http = VirtualClock(), MockHttp(jwks_response(key), jwks_response(key, rotated_key))
    provider = jwks_provider(http, clock, min_refetch_s=30)
    await provider.get_key("key-1")
    await clock.advance(31)
    assert (await provider.get_key("key-2")).key_id == "key-2"
    assert (await provider.get_key("key-1")).key_id == "key-1" and len(http.requests) == 2


async def test_concurrent_lookups_share_one_fetch(key):
    import asyncio

    http = MockHttp(jwks_response(key))
    provider = jwks_provider(http)
    keys = await asyncio.gather(*(provider.get_key("key-1") for _ in range(10)))
    assert len({id(k) for k in keys}) == 1 and len(http.requests) == 1


async def test_no_cache_and_no_endpoint_is_jwks_unavailable_without_hammering(key):
    clock, http = VirtualClock(), MockHttp(httpx.Response(503))
    provider = jwks_provider(http, clock, min_refetch_s=30)
    for _ in range(3):
        with pytest.raises(JwksUnavailable) as err:
            await provider.get_key("key-1")
    assert err.value.status_code == 503 and isinstance(err.value, WebhookRejected) and len(http.requests) == 1
    await clock.advance(31)
    with pytest.raises(JwksUnavailable):
        await provider.get_key("key-1")
    assert len(http.requests) == 2


async def test_a_stale_cache_survives_an_outage_for_a_bounded_time(key):
    clock = VirtualClock()
    http = MockHttp(jwks_response(key), httpx.Response(500))
    provider = jwks_provider(http, clock, ttl_s=100, min_refetch_s=10, stale_if_error_s=1000)
    await provider.get_key("key-1")
    await clock.advance(200)  # expired, refresh fails: the stale keys keep working
    assert (await provider.get_key("key-1")).key_id == "key-1"
    await clock.advance(1000)  # beyond ttl + stale window
    with pytest.raises(JwksUnavailable):
        await provider.get_key("key-1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://evil.example/keys"}),
        httpx.Response(404),
        httpx.Response(200, content=b"<html>"),
        httpx.Response(200, json={"keys": []}),
        httpx.Response(200, json={"nokeys": 1}),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, content=b" " * 300_000),
        httpx.ConnectError("boom"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_bad_jwks_responses_are_unavailable_and_redirects_are_never_followed(response):
    http = MockHttp(response)
    with pytest.raises(JwksUnavailable):
        await jwks_provider(http).get_key("key-1")
    assert len(http.requests) == 1 and str(http.requests[0].url) == JWKS_URL


async def test_only_strong_rsa_signing_keys_are_loaded(key, weak_key):
    ec = {
        "kty": "EC",
        "crv": "P-256",
        "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
        "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0",
        "kid": "ec",
    }
    oct_key = {"kty": "oct", "k": "c2VjcmV0", "kid": "oct"}
    document = {
        "keys": [
            key.jwk(),
            weak_key.jwk(),
            ec,
            oct_key,
            {**key.jwk(), "kid": "enc", "use": "enc"},
            {**key.jwk(), "kid": ""},
            {k: v for k, v in key.jwk().items() if k != "kid"},
            "not-a-key",
            {**key.jwk(), "kid": "alg-quirk", "alg": "RSA256"},
        ]
    }
    provider = jwks_provider(MockHttp(httpx.Response(200, json=document)))
    assert (await provider.get_key("key-1")).key_id == "key-1"
    assert (await provider.get_key("alg-quirk")).key_id == "alg-quirk"  # a quirky advertised alg does not hide the key
    for rejected in ("key-weak", "ec", "oct", "enc", ""):
        with pytest.raises(WebhookRejected, match="unknown signing key"):
            await provider.get_key(rejected)


@pytest.mark.parametrize(
    "url",
    [
        "http://plain.example/keys",
        "https://user:pw@example.com/keys",
        "https:///keys",
        "ftp://x/keys",
        "https://x/keys#frag",
    ],
)
def test_the_jwks_url_must_be_plain_https(url):
    with pytest.raises(ValueError):
        HttpJwksProvider(url, httpx.AsyncClient())


async def test_keys_are_never_trusted_from_anywhere_but_the_configured_url(key, other_key):
    # The attacker's key is published at the attacker's URL and named in the token header: it must never be fetched.
    http = MockHttp(jwks_response(key))
    v = JwtVerifier([ISS], [AUD], jwks_provider(http))
    forged = other_key.token(claims(ISS, AUD), headers={"jku": "https://evil.example/jwks"})
    assert await reason_of(v.verify(forged)) == "unsupported key reference"
    assert [str(r.url) for r in http.requests] == []
    assert await reason_of(v.verify(other_key.token(claims(ISS, AUD)))) == "invalid signature"
    assert {str(r.url) for r in http.requests} == {JWKS_URL}


async def test_end_to_end_verification_through_the_http_jwks(key):
    http = MockHttp(jwks_response(key))
    v = JwtVerifier([ISS], [AUD], jwks_provider(http))
    assert (await v.verify(key.token(claims(ISS, AUD))))["aud"] == AUD
    assert (await v.verify(key.token(claims(ISS, AUD))))["aud"] == AUD and len(http.requests) == 1


# ---------------------------------------------------------------------------------------- factories
async def test_the_acs_callback_verifier_uses_the_documented_issuer_jwks_and_audience(key, make_settings):
    http = MockHttp(jwks_response(key))
    v = acs_callback_verifier(make_settings(), http.client)
    assert (await v.verify(key.token(claims(ACS_ISSUER, ACS_RESOURCE))))["iss"] == ACS_ISSUER
    assert [str(r.url) for r in http.requests] == [ACS_JWKS_URL]
    assert ACS_JWKS_URL == "https://acscallautomation.communication.azure.com/calling/keys"
    assert (
        await reason_of(v.verify(key.token(claims("https://login.microsoftonline.com/x/v2.0", ACS_RESOURCE))))
        == "invalid issuer"
    )
    assert await reason_of(v.verify(key.token(claims(ACS_ISSUER, "another-resource")))) == "invalid audience"


async def test_acs_callback_tokens_are_limited_to_about_ten_minutes_unless_asked_otherwise(key, make_settings):
    import time

    now = int(time.time())
    day_long = key.token(claims(ACS_ISSUER, ACS_RESOURCE, exp=now + 86_400))
    v = acs_callback_verifier(make_settings(), MockHttp(jwks_response(key)).client)
    assert await reason_of(v.verify(day_long)) == "token lifetime too long"
    media = acs_callback_verifier(
        make_settings(), MockHttp(jwks_response(key)).client, max_lifetime_s=ACS_MEDIA_MAX_LIFETIME_S
    )
    assert (await media.verify(day_long))["iss"] == ACS_ISSUER


async def test_acs_hs256_and_none_tokens_are_rejected_by_the_factory_verifier(key, make_settings):
    v = acs_callback_verifier(make_settings(), MockHttp(jwks_response(key)).client)
    payload = claims(ACS_ISSUER, ACS_RESOURCE)
    assert await reason_of(v.verify(hs256_token(key.public_pem(), payload, "key-1"))) == "unsupported algorithm"
    assert await reason_of(v.verify(unsigned_token(payload, "key-1"))) == "unsupported algorithm"


async def test_several_acs_audiences_may_be_configured(key, make_settings):
    v = acs_callback_verifier(
        make_settings(acs_resource_id=" guid-form , /subscriptions/arm-form "), MockHttp(jwks_response(key)).client
    )
    for audience in ("guid-form", "/subscriptions/arm-form"):
        assert (await v.verify(key.token(claims(ACS_ISSUER, audience))))["aud"] == audience


def test_the_acs_verifier_needs_a_resource_id(make_settings):
    with pytest.raises(ConfigurationError, match="SPARTA_ACS_RESOURCE_ID"):
        acs_callback_verifier(make_settings(acs_resource_id=None), httpx.AsyncClient())


async def test_the_event_grid_verifier_uses_the_entra_issuer_jwks_audience_and_role(key, make_settings):
    http = MockHttp(jwks_response(key))
    v = event_grid_verifier(make_settings(), http.client)
    good = key.token(
        claims(f"https://login.microsoftonline.com/{TENANT}/v2.0", EVENT_GRID_AUDIENCE, roles=[EVENT_GRID_ROLE])
    )
    assert (await v.verify(good))["roles"] == [EVENT_GRID_ROLE]
    assert [str(r.url) for r in http.requests] == [f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"]
    v1 = key.token(claims(f"https://sts.windows.net/{TENANT}/", EVENT_GRID_AUDIENCE, roles=[EVENT_GRID_ROLE]))
    assert (await v.verify(v1))["iss"] == f"https://sts.windows.net/{TENANT}/"
    other_tenant = key.token(
        claims(
            "https://login.microsoftonline.com/99999999-2222-3333-4444-555555555555/v2.0",
            EVENT_GRID_AUDIENCE,
            roles=[EVENT_GRID_ROLE],
        )
    )
    assert await reason_of(v.verify(other_tenant)) == "invalid issuer"
    wrong_aud = key.token(
        claims(f"https://login.microsoftonline.com/{TENANT}/v2.0", "api://other", roles=[EVENT_GRID_ROLE])
    )
    assert await reason_of(v.verify(wrong_aud)) == "invalid audience"
    no_role = key.token(claims(f"https://login.microsoftonline.com/{TENANT}/v2.0", EVENT_GRID_AUDIENCE))
    assert await reason_of(v.verify(no_role)) == "missing required role"


async def test_the_event_grid_role_check_can_be_switched_off_if_live_tokens_lack_it(key, make_settings):
    v = event_grid_verifier(make_settings(), MockHttp(jwks_response(key)).client, required_role=None)
    token = key.token(claims(f"https://login.microsoftonline.com/{TENANT}/v2.0", EVENT_GRID_AUDIENCE))
    assert (await v.verify(token))["aud"] == EVENT_GRID_AUDIENCE


@pytest.mark.parametrize("tenant", [None, "", "common", "organizations", "contoso.onmicrosoft.com", "not-a-guid"])
def test_the_event_grid_verifier_needs_a_tenant_guid(make_settings, tenant):
    with pytest.raises(ConfigurationError, match="SPARTA_ENTRA_TENANT_ID"):
        event_grid_verifier(make_settings(entra_tenant_id=tenant), httpx.AsyncClient())


def test_the_event_grid_verifier_needs_an_audience_and_reports_every_problem(make_settings):
    with pytest.raises(ConfigurationError) as err:
        event_grid_verifier(make_settings(event_grid_audience=None, entra_tenant_id=None), httpx.AsyncClient())
    assert len(err.value.problems) == 2


# ------------------------------------------------------------------------------------- Event Grid
CALLER = "+919876543210"
CALLED = "+14255550123"


def incoming_event(**data_overrides) -> dict:
    data = {
        "to": {"kind": "phoneNumber", "rawId": f"4:{CALLED}", "phoneNumber": {"value": CALLED}},
        "from": {"kind": "phoneNumber", "rawId": f"4:{CALLER}", "phoneNumber": {"value": CALLER}},
        "serverCallId": "aHR0cHM6Ly9hcGkuZXhhbXBsZS9zZXJ2ZXJDYWxsSWQ",
        "callerDisplayName": "  Rahul \n Sharma\u202e ",
        "incomingCallContext": "eyJhbGciOiJub25lIn0.incoming-call-context-token",
        "correlationId": "corr-1234",
    }
    data.update(data_overrides)
    return {
        "id": "evt-1",
        "topic": "/subscriptions/s/resourceGroups/r/providers/Microsoft.Communication/communicationServices/acs",
        "subject": "/caller/x/recipient/y",
        "eventType": "Microsoft.Communication.IncomingCall",
        "eventTime": "2026-11-17T10:00:00.1234567Z",
        "dataVersion": "1.0",
        "metadataVersion": "1",
        "data": data,
    }


def body_of(*events) -> bytes:
    return json.dumps(list(events)).encode()


def test_an_event_grid_batch_is_parsed_and_unknown_fields_are_ignored():
    events = parse_event_grid(body_of(incoming_event(), {**incoming_event(), "id": "evt-2", "extra": {"x": 1}}))
    assert [e.id for e in events] == ["evt-1", "evt-2"] and isinstance(events[0], EventGridEvent)
    first = events[0]
    assert (first.eventType, first.dataVersion, first.eventTime) == (
        "Microsoft.Communication.IncomingCall",
        "1.0",
        "2026-11-17T10:00:00.1234567Z",
    )
    assert (
        first.topic.endswith("/acs")
        and first.subject == "/caller/x/recipient/y"
        and first.data["correlationId"] == "corr-1234"
    )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"\xff\xfe\x00",
        b"{}",
        b'"string"',
        b"[]",
        b"[1]",
        b'[{"id": "x"}]',
        b'[{"id": "", "eventType": "t"}]',
        b'[{"id": "x", "eventType": ""}]',
        b'[{"id": "x", "eventType": "t", "data": []}]',
        b'[{"id": "x", "eventType": "t", "data": "str"}]',
        b'[{"id": 5, "eventType": "t"}]',
        b'[{"id": "x", "eventType": "' + b"t" * 300 + b'"}]',
        b"[" * 100_000 + b"]" * 100_000,
    ],
)
def test_malformed_batches_are_rejected_with_a_400_and_a_static_reason(body):
    with pytest.raises(MalformedWebhookPayload) as err:
        parse_event_grid(body)
    assert err.value.status_code == 400 and err.value.reason in {
        "invalid JSON",
        "invalid event",
        "expected a non-empty event array",
    }


def test_size_and_count_limits_are_enforced():
    big = body_of({"id": "x", "eventType": "t", "data": {"blob": "y" * 2000}})
    with pytest.raises(MalformedWebhookPayload) as err:
        parse_event_grid(big, max_bytes=1000)
    assert err.value.status_code == 413 and err.value.reason == "payload too large"
    many = body_of(*[{"id": str(i), "eventType": "t"} for i in range(101)])
    with pytest.raises(MalformedWebhookPayload, match="non-empty event array"):
        parse_event_grid(many)
    assert len(parse_event_grid(many, max_events=200)) == 101
    with pytest.raises(MalformedWebhookPayload):
        parse_event_grid(b" " * 1_048_577)


def test_the_subscription_validation_handshake_is_answered_with_the_code():
    handshake = {
        "id": "hs-1",
        "topic": "/subscriptions/s",
        "subject": "",
        "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
        "data": {
            "validationCode": "512d38b6-c7b8-40c8-89fe-f46f9e9622b6",
            "validationUrl": "https://rp.example/validate?id=1",
        },
    }
    events = parse_event_grid(body_of(handshake))
    assert subscription_validation_response(events) == {"validationResponse": "512d38b6-c7b8-40c8-89fe-f46f9e9622b6"}
    assert subscription_validation_response(parse_event_grid(body_of(incoming_event()))) is None


@pytest.mark.parametrize("code", [None, 12345, "", "x" * 300, "has space", "a/b", {"a": 1}])
def test_an_invalid_validation_code_is_rejected(code):
    event = {
        "id": "hs",
        "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
        "data": {"validationCode": code},
    }
    with pytest.raises(MalformedWebhookPayload, match="invalid validation code"):
        subscription_validation_response(parse_event_grid(body_of(event)))


NOW_DT = datetime(2026, 11, 17, 10, 0, 1, tzinfo=UTC)


def test_an_incoming_call_event_maps_to_an_incoming_call():
    call = incoming_call_from_event(parse_event_grid(body_of(incoming_event()))[0], NOW_DT)
    assert isinstance(call, IncomingCall)
    assert call.provider == "azure" and call.provider_call_id == "aHR0cHM6Ly9hcGkuZXhhbXBsZS9zZXJ2ZXJDYWxsSWQ"
    assert (call.caller_number, call.called_number) == (CALLER, CALLED)
    assert call.display_name == "Rahul Sharma" and call.correlation_id == "corr-1234"
    assert call.context == "eyJhbGciOiJub25lIn0.incoming-call-context-token" and call.received_at == NOW_DT


def test_identifiers_fall_back_to_the_raw_id_and_non_phone_callers_have_no_number():
    only_raw = {"kind": "phoneNumber", "rawId": f"4:{CALLER}"}
    acs_user = {
        "kind": "communicationUser",
        "rawId": "8:acs:resource_user",
        "communicationUser": {"id": "8:acs:resource_user"},
    }
    event = parse_event_grid(body_of(incoming_event(**{"from": only_raw, "to": acs_user})))[0]
    call = incoming_call_from_event(event, NOW_DT)
    assert call.caller_number == CALLER and call.called_number is None


@pytest.mark.parametrize(
    "bad", ["anonymous", "", "+", "12", "+1234567890123456", "98765abc", "<script>", None, 5, {"x": 1}]
)
def test_junk_numbers_are_dropped_rather_than_passed_on(bad):
    event = parse_event_grid(
        body_of(incoming_event(**{"from": {"kind": "phoneNumber", "phoneNumber": {"value": bad}}}))
    )[0]
    assert incoming_call_from_event(event, NOW_DT).caller_number is None


def test_display_names_are_cleaned_and_bounded():
    event = parse_event_grid(body_of(incoming_event(callerDisplayName="\x00\u200b  " + "N" * 200)))[0]
    assert incoming_call_from_event(event, NOW_DT).display_name == "N" * 64
    blank = parse_event_grid(body_of(incoming_event(callerDisplayName="\u202e \n")))[0]
    assert incoming_call_from_event(blank, NOW_DT).display_name is None
    missing = incoming_event()
    del missing["data"]["callerDisplayName"]
    assert incoming_call_from_event(parse_event_grid(body_of(missing))[0], NOW_DT).display_name is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"incomingCallContext": None},
        {"incomingCallContext": ""},
        {"incomingCallContext": "c" * 9000},
        {"incomingCallContext": 5},
        {"serverCallId": None},
        {"serverCallId": ""},
        {"serverCallId": "s" * 600},
    ],
)
def test_an_incomplete_incoming_call_event_is_malformed(overrides):
    event = parse_event_grid(body_of(incoming_event(**overrides)))[0]
    with pytest.raises(MalformedWebhookPayload, match="incomplete") as err:
        incoming_call_from_event(event, NOW_DT)
    assert CALLER not in err.value.reason


def test_other_event_types_are_not_incoming_calls():
    other = {**incoming_event(), "eventType": "Microsoft.Communication.CallEnded"}
    with pytest.raises(MalformedWebhookPayload, match="not an incoming call event"):
        incoming_call_from_event(parse_event_grid(body_of(other))[0], NOW_DT)


async def test_nothing_in_the_webhook_path_logs_phone_numbers_or_tokens(key, caplog):
    caplog.set_level(logging.DEBUG)
    events = parse_event_grid(body_of(incoming_event()))
    incoming_call_from_event(events[0], NOW_DT)
    token = key.token(claims(ISS, AUD))
    await JwtVerifier([ISS], [AUD], StaticJwks(key)).verify(token)
    with pytest.raises(WebhookRejected):
        await JwtVerifier([ISS], [AUD], StaticJwks(key)).verify(token[:-6] + "AAAAAA")
    await check_hmac()
    assert CALLER not in caplog.text and CALLED not in caplog.text and token not in caplog.text
