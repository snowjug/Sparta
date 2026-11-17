"""Test doubles shared by the Azure adapter tests: a scripted HTTP transport and a clock that never waits."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

Scripted = httpx.Response | Callable[[httpx.Request], httpx.Response] | Exception


class FastClock:
    """Sleeps instantly but records every requested delay, so back-off is asserted exactly and nothing waits."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        await asyncio.sleep(0)


class MockHttp:
    """An ``httpx.AsyncClient`` over a scripted ``MockTransport``. The last scripted item repeats once reached."""

    def __init__(self, *script: Scripted) -> None:
        self.requests: list[httpx.Request] = []
        self._script = list(script)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return httpx.Response(item.status_code, headers=item.headers, content=item.content)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def multipart_parts(request: httpx.Request) -> dict[str, tuple[dict[str, str], bytes]]:
    """Split a multipart/form-data request into ``{field name: (lower-cased part headers, body)}``."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts: dict[str, tuple[dict[str, str], bytes]] = {}
    for raw in request.content.split(b"--" + boundary)[1:-1]:
        head, _, body = raw[2:-2].partition(b"\r\n\r\n")
        headers = dict(line.decode().split(": ", maxsplit=1) for line in head.split(b"\r\n"))
        lowered = {k.lower(): v for k, v in headers.items()}
        name = lowered["content-disposition"].split('name="')[1].split('"')[0]
        parts[name] = (lowered, body)
    return parts
