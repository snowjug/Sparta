"""Security behaviour of the HTTP layer: authentication, isolation, headers, CORS, limits and host checks."""

import base64
import hashlib
import time

import httpx
import jwt
import pytest
from fastapi.routing import APIRoute
from jwt_kit import Idp

from conftest import DELIVERY, SCAM, ApiEnv, running_env
from sparta.api.auth import DevAuthenticator, OidcAuthenticator, subject_to_user_id
from sparta.api.routers import account, calls, safety, screening, simulator, system, webhooks
from sparta.api.routers import live as live_router
from sparta.config import ConfigurationError, Environment, Settings

API = "/api/v1"
ISSUER = "https://login.example.test/tenant/v2.0"
AUDIENCE = "api://sparta"


# ---------------------------------------------------------------------------------------------- OIDC kit
@pytest.fixture(scope="module")
def idp() -> Idp:
    return Idp(ISSUER, AUDIENCE)


async def oidc_env(idp: Idp, **overrides: object):  # type: ignore[no-untyped-def]
    ctx = running_env(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE, **overrides)
    env = await ctx.__aenter__()
    env.app.state.authenticator = OidcAuthenticator(env.container.settings, None, jwks=idp.jwks())
    return ctx, env


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------------------------------------- OIDC
async def test_a_valid_token_authenticates_and_names_the_owner(idp: Idp):
    ctx, env = await oidc_env(idp)
    try:
        r = await env.client.get(f"{API}/me", headers=bearer(idp.token()))
        assert r.status_code == 200
        assert r.json() == {"id": "user-a", "display_name": "Alice A", "auth_mode": "oidc"}
        status = (await env.client.get(f"{API}/system/status")).json()
        assert status["auth_mode"] == "oidc" and status["dev_banner"] is False
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.parametrize(
    "case",
    [
        "no_header",
        "not_bearer",
        "garbage",
        "expired",
        "not_yet_valid",
        "wrong_audience",
        "wrong_issuer",
        "no_subject",
        "no_expiry",
        "alg_none",
        "hs256_with_public_key",
        "signed_by_another_key",
        "unknown_kid",
    ],
)
async def test_invalid_tokens_are_rejected_with_a_generic_401(idp: Idp, case: str):
    ctx, env = await oidc_env(idp)
    try:
        now = int(time.time())
        other = Idp(ISSUER, AUDIENCE)
        headers: dict[str, str]
        match case:
            case "no_header":
                headers = {}
            case "not_bearer":
                headers = {"Authorization": f"Basic {base64.b64encode(b'a:b').decode()}"}
            case "garbage":
                headers = bearer("not.a.jwt")
            case "expired":
                headers = bearer(idp.token(exp=now - 3600, iat=now - 7200, nbf=now - 7200))
            case "not_yet_valid":
                headers = bearer(idp.token(nbf=now + 3600, iat=now + 3600, exp=now + 7200))
            case "wrong_audience":
                headers = bearer(idp.token(aud="api://someone-else"))
            case "wrong_issuer":
                headers = bearer(idp.token(iss="https://evil.example/"))
            case "no_subject":
                headers = bearer(idp.token(sub=None))
            case "no_expiry":
                headers = bearer(idp.token(exp=None))
            case "alg_none":
                headers = bearer(idp.unsigned_token())
            case "hs256_with_public_key":
                headers = bearer(idp.hs256_confusion_token())
            case "signed_by_another_key":
                headers = bearer(other.token())
            case "unknown_kid":
                headers = bearer(
                    jwt.encode(
                        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": now + 60},
                        idp.private,
                        algorithm="RS256",
                        headers={"kid": "nope"},
                    )
                )
            case _:
                raise AssertionError(case)
        r = await env.client.get(f"{API}/me", headers=headers)
        assert r.status_code == 401, (case, r.text)
        assert r.json()["error"]["code"] == "unauthorized" and r.headers["www-authenticate"] == "Bearer"
        assert "signature" not in r.text.lower() and "audience" not in r.text.lower()  # no oracle for attackers
    finally:
        await ctx.__aexit__(None, None, None)


async def test_the_dev_header_has_no_effect_in_oidc_mode(idp: Idp):
    ctx, env = await oidc_env(idp)
    try:
        anonymous = await env.client.get(f"{API}/me", headers={"X-Sparta-Dev-User": "dev-owner"})
        assert anonymous.status_code == 401
        spoof = await env.client.get(f"{API}/me", headers={**bearer(idp.token()), "X-Sparta-Dev-User": "victim"})
        assert spoof.json()["id"] == "user-a"
    finally:
        await ctx.__aexit__(None, None, None)


async def test_one_owner_cannot_touch_another_owners_calls_with_real_tokens(idp: Idp):
    ctx, env = await oidc_env(idp)
    try:
        alice, mallory = bearer(idp.token(sub="alice")), bearer(idp.token(sub="mallory"))
        created = await env.client.post(f"{API}/calls", json={"silence_timers": "off"}, headers=alice)
        assert created.status_code == 201
        call_id = created.json()["id"]
        assert (await env.client.get(f"{API}/calls/{call_id}", headers=alice)).status_code == 200
        assert (await env.client.get(f"{API}/calls/{call_id}", headers=mallory)).status_code == 404
        assert (await env.client.get(f"{API}/calls", headers=mallory)).json()["items"] == []
    finally:
        await ctx.__aexit__(None, None, None)


def test_subjects_are_stored_safely():
    assert subject_to_user_id("auth0|abc123") == "u_" + hashlib.sha256(b"auth0|abc123").hexdigest()[:40]
    assert subject_to_user_id("11111111-2222-3333-4444-555555555555") == "11111111-2222-3333-4444-555555555555"
    long_subject = "x" * 500
    assert len(subject_to_user_id(long_subject)) == 42


def test_dev_authentication_cannot_be_constructed_in_production():
    with pytest.raises(ConfigurationError):
        Settings(_env_file=None, env="production", auth_mode="dev")  # type: ignore[call-arg]
    settings = Settings(_env_file=None, env="test")  # type: ignore[call-arg]
    production_like = settings.model_copy(update={"env": Environment.PRODUCTION})  # skips validators on purpose
    with pytest.raises(ConfigurationError):
        DevAuthenticator(production_like)


# ------------------------------------------------------------------------------------------ dev identity
@pytest.mark.parametrize("value", ["../etc/passwd", "a b", "x" * 65, "semi;colon", "new\nline", "<script>"])
async def test_the_dev_user_header_must_be_a_plain_identifier(env: ApiEnv, value: str):
    try:
        r = await env.client.get(f"{API}/me", headers={"X-Sparta-Dev-User": value})
    except (httpx.InvalidURL, ValueError, httpx.LocalProtocolError):
        return  # the client library itself refuses header injection
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


# ----------------------------------------------------------------------------------- anonymous-access sweep
PUBLIC = {f"{API}/system/status", "/healthz", "/readyz", "/metrics"}


def _concrete(path: str) -> str:
    return path.replace("{call_id}", "call_x1").replace("{entry_id}", "entry_x1")


def _owner_routes() -> list[APIRoute]:
    """Every authenticated REST route, taken from the routers themselves (stable public API)."""
    routes: list[APIRoute] = []
    for module in (system, calls, live_router, account, safety, simulator, screening):
        routes += [r for r in module.router.routes if isinstance(r, APIRoute)]
    return routes


async def test_every_non_public_route_rejects_anonymous_callers(idp: Idp):
    ctx, env = await oidc_env(idp)
    try:
        checked = 0
        for route in _owner_routes():
            full = f"{API}{route.path}"
            if full in PUBLIC:
                continue
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                r = await env.client.request(method, _concrete(full))
                assert r.status_code == 401, f"{method} {full} answered {r.status_code} without credentials"
                checked += 1
        assert checked >= 45  # the sweep must not silently shrink if routes are renamed
    finally:
        await ctx.__aexit__(None, None, None)


def test_only_provider_callbacks_are_hidden_from_the_api_document():
    hidden = {
        f"{API}{r.path}"
        for module in (system, calls, live_router, account, safety, simulator, screening, webhooks)
        for r in module.router.routes
        if isinstance(r, APIRoute) and not r.include_in_schema
    }
    assert hidden == {
        f"{API}/webhooks/acs/events",
        f"{API}/webhooks/acs/callbacks/{{call_id}}",
        f"{API}/webhooks/twilio/voice",
        f"{API}/webhooks/twilio/status",
        f"{API}/webhooks/asterisk/incoming",
        f"{API}/webhooks/asterisk/next",
        f"{API}/webhooks/asterisk/ended",
        f"{API}/webhooks/generic",
    }


# --------------------------------------------------------------------------------------- owner isolation
def _render(template: str, body: dict | None, call_id: str) -> tuple[str, dict | None]:
    payload = (
        None
        if body is None
        else {k: (v.replace("{id}", call_id) if isinstance(v, str) else v) for k, v in body.items()}
    )
    return f"{API}{template.replace('{id}', call_id)}", payload


async def test_another_owners_call_is_indistinguishable_from_a_missing_call(env: ApiEnv):
    mine = await env.new_call(user="owner-a")
    await env.say(mine["id"], DELIVERY, user="owner-a")
    stranger = {"X-Sparta-Dev-User": "owner-b"}
    probes = [
        ("GET", "/calls/{id}", None),
        ("GET", "/calls/{id}/events", None),
        ("GET", "/calls/{id}/report", None),
        ("GET", "/calls/{id}/export", None),
        ("POST", "/calls/{id}/turns", {"text": "hello"}),
        ("POST", "/calls/{id}/partial", {"text": "hello"}),
        ("POST", "/calls/{id}/interrupt", {}),
        ("POST", "/calls/{id}/silence", {}),
        ("POST", "/calls/{id}/takeover", {}),
        ("POST", "/calls/{id}/continue", {}),
        ("POST", "/calls/{id}/end", {}),
        ("POST", "/calls/{id}/block", {}),
        ("POST", "/calls/{id}/trust", {}),
        ("POST", "/calls/{id}/feedback", {"kind": "was_spam"}),
        ("DELETE", "/calls/{id}/content", None),
        ("DELETE", "/calls/{id}", None),
        ("POST", "/live/ticket", {"call_id": "{id}"}),
    ]
    for method, template, body in probes:
        real_url, real_body = _render(template, body, mine["id"])
        ghost_url, ghost_body = _render(template, body, "call_doesnotexist")
        theirs = await env.client.request(method, real_url, json=real_body, headers=stranger)
        ghost = await env.client.request(method, ghost_url, json=ghost_body, headers=stranger)
        assert theirs.status_code == ghost.status_code == 404, (method, template, theirs.status_code, theirs.text)
        assert theirs.json()["error"]["code"] == ghost.json()["error"]["code"]
        assert theirs.json()["error"]["message"] == ghost.json()["error"]["message"]  # no existence oracle
    assert (
        await env.client.get(f"{API}/calls/{mine['id']}", headers={"X-Sparta-Dev-User": "owner-a"})
    ).status_code == 200
    assert (
        await env.client.get(f"{API}/calls/{mine['id']}")
    ).status_code == 404  # the default dev owner is another owner


async def test_lists_and_settings_are_per_owner(env: ApiEnv):
    a, b = {"X-Sparta-Dev-User": "owner-a"}, {"X-Sparta-Dev-User": "owner-b"}
    await env.client.post(f"{API}/blocked-callers", json={"number": "+919800000041"}, headers=a)
    assert (await env.client.get(f"{API}/blocked-callers", headers=b)).json() == []
    prefs = (await env.client.get(f"{API}/preferences", headers=a)).json()
    prefs["strictness"] = "strict"
    await env.client.put(f"{API}/preferences", json=prefs, headers=a)
    assert (await env.client.get(f"{API}/preferences", headers=b)).json()["strictness"] == "balanced"
    assert (await env.client.get(f"{API}/audit", headers=b)).json() == []
    entry = (await env.client.get(f"{API}/blocked-callers", headers=a)).json()[0]
    assert (await env.client.delete(f"{API}/blocked-callers/{entry['id']}", headers=b)).status_code == 404


# ------------------------------------------------------------------------------------------ transport
async def test_security_headers_are_present_on_success_and_error_responses(env: ApiEnv):
    for path in (f"{API}/system/status", f"{API}/calls/call_unknown", f"{API}/nope", "/healthz"):
        r = await env.client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert r.headers["referrer-policy"] == "no-referrer" and r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store" and "default-src 'none'" in r.headers["content-security-policy"]
        assert "microphone=()" in r.headers["permissions-policy"] and "x-request-id" in r.headers
    assert "strict-transport-security" not in (await env.client.get("/healthz")).headers  # only in production


async def test_cors_allows_only_configured_origins(env: ApiEnv):
    ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,idempotency-key"}
    ok = await env.client.options(f"{API}/calls", headers={"Origin": "http://localhost:3000", **ask})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in ok.headers  # bearer tokens, never cookies
    evil = await env.client.options(f"{API}/calls", headers={"Origin": "https://evil.example", **ask})
    assert "access-control-allow-origin" not in evil.headers and evil.status_code == 400
    plain = await env.client.get(f"{API}/system/status", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in plain.headers
    exposed = (await env.client.get(f"{API}/me", headers={"Origin": "http://localhost:3000"})).headers
    for name in ("Retry-After", "X-Request-ID", "Content-Disposition", "Idempotent-Replayed"):
        assert name.lower() in exposed["access-control-expose-headers"].lower()


async def test_unexpected_errors_are_hidden_but_still_carry_cors_headers():
    async with running_env() as env:

        async def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("database password is hunter2")

        env.container.owner.home = boom  # type: ignore[method-assign]
        r = await env.client.get(f"{API}/home", headers={"Origin": "http://localhost:3000"})
        assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
        assert "hunter2" not in r.text and r.json()["error"]["trace_id"]
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_oversized_bodies_are_rejected_before_they_are_parsed():
    async with running_env(max_request_bytes=2000) as env:
        call = await env.new_call()
        big = {"text": "x" * 3000}
        declared = await env.client.post(f"{API}/calls/{call['id']}/turns", json=big)
        assert declared.status_code == 413 and declared.json()["error"]["code"] == "payload_too_large"

        async def chunks():  # no Content-Length: the limit must still hold
            for _ in range(4):
                yield b'{"text": "' + b"y" * 900 + b'"}'

        streamed = await env.client.post(
            f"{API}/calls/{call['id']}/turns", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert streamed.status_code == 413
        assert (await env.client.post(f"{API}/calls/{call['id']}/turns", json={"text": "short"})).status_code == 200


async def test_the_host_header_is_checked_when_trusted_hosts_are_configured():
    async with running_env(trusted_hosts=["testserver"]) as env:
        assert (await env.client.get("/healthz")).status_code == 200
        evil = await env.client.get("/healthz", headers={"Host": "evil.example"})
        assert evil.status_code == 400


async def test_docs_are_not_served_in_production_configuration():
    from sparta.api.main import create_app

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="production",
        auth_mode="oidc",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        data_keys="Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm8=",
        pepper="pepper-pepper-pepper-1234",
        webhook_secret="webhook-secret-123456",
        database_url="postgresql+asyncpg://u:p@db/sparta",
        redis_url="redis://cache:6379/0",
        cors_origins=["https://app.example.test"],
        trusted_hosts=["api.example.test"],
    )
    app = create_app(settings)
    assert app.docs_url is None and app.openapi_url is None and app.redoc_url is None


async def test_scam_and_delivery_text_never_appear_in_error_responses_or_headers(env: ApiEnv):
    call = await env.new_call()
    r = await env.client.post(f"{API}/calls/{call['id']}/turns", json={"text": SCAM, "bogus": True})
    assert r.status_code == 422 and "OTP" not in r.text and "State Bank" not in r.text
    assert all("State Bank" not in v for v in r.headers.values())
