"""A development tunnel must serve provider callbacks only, never the owner API of a development-identity server."""

import pytest

from conftest import running_env
from sparta.api.middleware import ProviderOnlyHostsMiddleware
from sparta.config import ConfigurationError

TUNNEL = "sparta-dev.example.net"


class Recorder:
    """A stand-in ASGI app: remembers which requests got through the guard."""

    def __init__(self) -> None:
        self.reached: list[tuple[str, str]] = []

    async def __call__(self, scope, receive, send):
        self.reached.append((scope["type"], scope["path"]))
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def scope(kind: str, path: str, host: str | None) -> dict:
    headers = [(b"host", host.encode())] if host else []
    return {
        "type": kind,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws" if kind == "websocket" else "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "headers": headers,
        "method": "GET",
        "query_string": b"",
        "client": ("203.0.113.9", 4000),
        "server": ("testserver", 80),
    }


async def run(guard, kind, path, host):
    sent: list[dict] = []

    async def receive():
        return {"type": "websocket.connect"} if kind == "websocket" else {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    await guard(scope(kind, path, host), receive, send)
    return sent


@pytest.mark.parametrize(
    ("path", "reaches"),
    [
        ("/healthz", True),
        ("/readyz", True),
        ("/api/v1/webhooks/acs/events", True),
        ("/api/v1/webhooks/acs/callbacks/call_abc", True),
        ("/api/v1/media/acs/call_abc", True),
        ("/api/v1/me", False),
        ("/api/v1/calls", False),
        ("/api/v1/webhooksx", False),
        ("/api/v1/media", False),
        ("/docs", False),
        ("/api/v1/openapi.json", False),
        ("/healthz/extra", False),
        ("/", False),
    ],
)
async def test_only_provider_paths_exist_on_a_listed_host(path, reaches):
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL.upper()])
    sent = await run(guard, "http", path, f"{TUNNEL}:443")
    assert bool(inner.reached) is reaches
    assert sent[0]["status"] == (200 if reaches else 404)


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1", "other.example.net", "[::1]:8000"])
async def test_other_hosts_are_untouched(host):
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL])
    sent = await run(guard, "http", "/api/v1/me", host)
    assert inner.reached == [("http", "/api/v1/me")] and sent[0]["status"] == 200


@pytest.mark.parametrize(
    "host",
    [
        TUNNEL,
        TUNNEL.upper(),
        f"{TUNNEL}.",  # the absolute form of the same name
        f"{TUNNEL}:443",
        f"{TUNNEL.upper()}.:8443",
    ],
)
async def test_the_listed_host_is_matched_as_a_name_however_it_is_written(host):
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL])
    sent = await run(guard, "http", "/api/v1/me", host)
    assert inner.reached == [] and sent[0]["status"] == 404
    assert (await run(guard, "http", "/healthz", host))[0]["status"] == 200


@pytest.mark.parametrize(
    "host",
    [None, f"{TUNNEL}:1:2", f"{TUNNEL}::", f"https://{TUNNEL}", f"{TUNNEL}%2e", "bad host", f"{TUNNEL}:99999999"],
)
async def test_a_missing_or_malformed_host_is_treated_like_a_listed_one(host):
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL])
    sent = await run(guard, "http", "/api/v1/calls", host)
    assert inner.reached == [] and sent[0]["status"] == 404
    assert (await run(guard, "websocket", "/api/v1/live/calls/call_abc", host)) == [
        {"type": "websocket.close", "code": 1008}
    ]
    assert (await run(guard, "http", "/readyz", host))[0]["status"] == 200


@pytest.mark.parametrize("entry", [f"https://{TUNNEL}", f"{TUNNEL}/path", "two words", f"{TUNNEL}:1:2"])
def test_a_configured_host_that_is_not_a_host_name_is_refused_instead_of_silently_guarding_nothing(entry):
    with pytest.raises(ValueError, match="not a host name"):
        ProviderOnlyHostsMiddleware(Recorder(), hosts=[entry])


async def test_a_media_socket_is_allowed_and_any_other_websocket_is_refused_before_it_is_accepted():
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL])
    await run(guard, "websocket", "/api/v1/media/acs/call_abc", TUNNEL)
    assert inner.reached == [("websocket", "/api/v1/media/acs/call_abc")]
    sent = await run(guard, "websocket", "/api/v1/live/calls/call_abc", TUNNEL)
    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert len(inner.reached) == 1


async def test_no_listed_hosts_means_no_filtering():
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[])
    await run(guard, "http", "/api/v1/me", TUNNEL)
    await run(guard, "http", "/api/v1/me", None)
    assert inner.reached == [("http", "/api/v1/me")] * 2


async def test_the_real_app_hides_the_owner_api_on_the_tunnel_host_but_not_locally():
    async with running_env(provider_only_hosts=[TUNNEL], trusted_hosts=[TUNNEL, "testserver"]) as env:
        local = await env.client.get("/api/v1/me")
        assert local.status_code == 200
        tunnel = await env.client.get("/api/v1/me", headers={"Host": TUNNEL})
        assert tunnel.status_code == 404 and tunnel.json()["error"]["code"] == "not_found"
        assert (await env.client.get("/docs", headers={"Host": TUNNEL})).status_code == 404
        assert (await env.client.get("/healthz", headers={"Host": TUNNEL})).status_code == 200
        calls = await env.client.get("/api/v1/calls", headers={"Host": TUNNEL, "X-Sparta-Dev-User": "x"})
        assert calls.status_code == 404
        # every spelling of the tunnel host that is not the listed one is refused by trusted hosts, never served
        for host in (f"{TUNNEL}.", f"{TUNNEL}:1:2", f"alias-of-{TUNNEL}"):
            other = await env.client.get("/api/v1/me", headers={"Host": host})
            assert other.status_code == 400, host


async def test_the_server_refuses_to_start_when_provider_only_hosts_are_not_backed_by_explicit_trusted_hosts():
    with pytest.raises(ConfigurationError, match="SPARTA_TRUSTED_HOSTS"):
        async with running_env(provider_only_hosts=[TUNNEL]):
            pytest.fail("the server started with a wildcard of trusted hosts")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/webhooks/../me",  # the path exactly as a server delivers it: dot segments are not collapsed
        "/api/v1/webhooks/../../calls",
        "/api/v1/media/../calls",
        "/api/v1/webhooks/;/../me",
        "/api/v1/webhooks/%2e%2e/me",
        "/api/v1/webhooks/acs/..%2f..%2fme",
        "//api/v1/me",
        "/API/V1/ME",
        "/api/v1/webhooks",
        "/api/v1/media",
    ],
)
async def test_a_path_that_only_looks_like_a_provider_path_never_reaches_an_owner_route(path):
    """Raw ASGI scopes against the whole app (an HTTP client would normalise the dot segments before sending)."""
    async with running_env(provider_only_hosts=[TUNNEL], trusted_hosts=[TUNNEL, "testserver"]) as env:
        sent = await run(env.app, "http", path, TUNNEL)
        assert sent[0]["status"] == 404, path
        owner_only = await run(env.app, "http", "/api/v1/me", "testserver")
        assert owner_only[0]["status"] == 200  # the same server still serves the owner API locally
