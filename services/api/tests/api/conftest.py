"""Fixtures for HTTP-level tests: the real app over an in-memory database and a virtual clock."""

import asyncio
import io
import sys
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest_asyncio
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))

from call_harness import make_settings

from sparta.api.main import create_app
from sparta.clock import VirtualClock
from sparta.services.calls import CallService
from sparta.services.container import Container
from sparta.services.notifier import RecordingPushNotifier

SCAM = "Hello, this is Rahul from State Bank of India. Please share the OTP sent to your phone."
DELIVERY = (
    "Hello, I am calling from Amazon delivery. I am outside your building with your parcel, can someone come down?"
)


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


@dataclass
class ApiEnv:
    container: Container
    app: FastAPI
    client: httpx.AsyncClient
    clock: VirtualClock

    @property
    def calls(self) -> CallService:
        return self.container.calls

    async def idle(self, rounds: int = 400) -> None:
        stable = 0
        for _ in range(rounds):
            await asyncio.sleep(0.004)
            busy = any(rt.lock.locked() for rt in self.container.calls._runtimes.values())
            stable = 0 if busy else stable + 1
            if stable >= 4:
                return
        raise AssertionError("background call work did not go idle")

    async def advance(self, seconds: float) -> None:
        await self.clock.advance(seconds)
        await self.idle()

    async def new_call(self, user: str | None = None, **body: object) -> dict:
        body.setdefault("silence_timers", "off")
        headers = {"X-Sparta-Dev-User": user} if user else None
        r = await self.client.post("/api/v1/calls", json=body, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()

    async def say(self, call_id: str, text: str, user: str | None = None, **body: object) -> httpx.Response:
        headers = {"X-Sparta-Dev-User": user} if user else None
        return await self.client.post(f"/api/v1/calls/{call_id}/turns", json={"text": text, **body}, headers=headers)


@asynccontextmanager
async def running_env(**overrides: object) -> AsyncIterator[ApiEnv]:
    settings = make_settings(**overrides)
    clock = VirtualClock()
    container = await Container.build(settings, clock=clock, notifier=RecordingPushNotifier())
    await container.start()
    app = create_app(settings, container=container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            yield ApiEnv(container, app, client, clock)
        finally:
            await container.stop()


@pytest_asyncio.fixture
async def env() -> AsyncIterator[ApiEnv]:
    async with running_env() as e:
        yield e


@dataclass
class LiveServer:
    env: ApiEnv
    base: str  # http://127.0.0.1:PORT
    ws_base: str  # ws://127.0.0.1:PORT


@asynccontextmanager
async def serving(env: ApiEnv) -> AsyncIterator[LiveServer]:
    """Serve ``env.app`` on an ephemeral localhost port so real WebSocket clients can connect."""
    config = uvicorn.Config(env.app, host="127.0.0.1", port=0, log_config=None, lifespan="off", access_log=False)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("test server did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield LiveServer(env, f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


@pytest_asyncio.fixture
async def live(env: ApiEnv) -> AsyncIterator[LiveServer]:
    async with serving(env) as server:
        yield server
