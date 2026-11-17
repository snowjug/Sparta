"""Shared fixtures."""

import os
import tempfile

import pytest

# Keep tests hermetic: never read a developer's .env and never write under the repo.
os.environ.setdefault("SPARTA_ENV", "test")
os.environ.setdefault("SPARTA_LOG_JSON", "false")
os.environ.setdefault("SPARTA_DATA_DIR", tempfile.mkdtemp(prefix="sparta-test-"))

from sparta.clock import VirtualClock
from sparta.orchestrator.engine import ConversationEngine, EngineConfig


@pytest.fixture(scope="session")
def engine() -> ConversationEngine:
    return ConversationEngine()


@pytest.fixture
def cfg() -> EngineConfig:
    return EngineConfig(call_id="call_test0001", owner_name="Atharv")


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock()
