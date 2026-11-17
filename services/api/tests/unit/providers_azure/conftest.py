"""Fixtures for the Azure adapter tests. No network: every HTTP call goes through ``httpx.MockTransport``."""

from collections.abc import Callable

import pytest

from sparta.config import Settings

from .helpers import FastClock


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "azure_speech_key": "test-speech-key",
            "azure_speech_region": "centralindia",
            "azure_openai_endpoint": "https://sparta-test.openai.azure.com",
            "azure_openai_key": "test-openai-key",
            "azure_openai_deployment": "gpt-4o-mini",
            "provider_timeout_s": 1.0,
            "provider_max_retries": 2,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return make


@pytest.fixture
def fast_clock() -> FastClock:
    return FastClock()
