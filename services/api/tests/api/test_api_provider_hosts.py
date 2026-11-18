"""A development tunnel must serve provider callbacks only, never the owner API of a development-identity server."""

import pytest

from conftest import running_env
from sparta.api.middleware import ProviderOnlyHostsMiddleware

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
    return {"type": kind, "path": path, "headers": headers, "method": "GET", "query_string": b""}


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


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1", None, "other.example.net"])
async def test_other_hosts_are_untouched(host):
    inner = Recorder()
    guard = ProviderOnlyHostsMiddleware(inner, hosts=[TUNNEL])
    sent = await run(guard, "http", "/api/v1/me", host)
    assert inner.reached == [("http", "/api/v1/me")] and sent[0]["status"] == 200


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
    assert inner.reached == [("http", "/api/v1/me")]


async def test_the_real_app_hides_the_owner_api_on_the_tunnel_host_but_not_locally():
    async with running_env(provider_only_hosts=[TUNNEL]) as env:
        local = await env.client.get("/api/v1/me")
        assert local.status_code == 200
        tunnel = await env.client.get("/api/v1/me", headers={"Host": TUNNEL})
        assert tunnel.status_code == 404 and tunnel.json()["error"]["code"] == "not_found"
        assert (await env.client.get("/docs", headers={"Host": TUNNEL})).status_code == 404
        assert (await env.client.get("/healthz", headers={"Host": TUNNEL})).status_code == 200
        calls = await env.client.get("/api/v1/calls", headers={"Host": TUNNEL, "X-Sparta-Dev-User": "x"})
        assert calls.status_code == 404
