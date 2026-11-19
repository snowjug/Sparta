"""Fixtures for the local speech tests. No network, no model: the engines are faked unless a test says otherwise."""

import os
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sparta.config import Settings

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ENGINE_ENVIRONMENT = ("HF_HUB_OFFLINE", "ORT_DISABLE_TELEMETRY")


@pytest.fixture(autouse=True)
def engine_environment() -> Iterator[None]:
    """The providers set these two variables for the whole process: start each test without them, leave none behind."""
    saved = {name: os.environ.pop(name, None) for name in ENGINE_ENVIRONMENT}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    def make(**overrides: object) -> Settings:
        values: dict[str, object] = {"local_model_dir": str(tmp_path / "models")}
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return make


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any attempt to reach another machine (or resolve a name) fails the test; the list records what was attempted.

    Loopback stays open: asyncio's own wake-up socket pair on Windows connects to it."""
    attempts: list[str] = []
    real_connect = socket.socket.connect

    def refuse(*args: object, **kwargs: object) -> None:
        attempts.append(repr(args[:2]))
        raise AssertionError("the local speech providers must never use the network")

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host in LOOPBACK:
            real_connect(self, address)  # type: ignore[arg-type]
            return
        refuse(address)

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts
