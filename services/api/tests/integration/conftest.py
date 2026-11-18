"""Fixtures for end-to-end call-service tests (hermetic container: in-memory DB, virtual clock)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from call_harness import Harness, running_container

from sparta.services.container import Container


@pytest_asyncio.fixture
async def container() -> AsyncIterator[Container]:
    async with running_container() as c:
        yield c


@pytest_asyncio.fixture
async def h(container: Container) -> Harness:
    return Harness(container)
