"""Fixtures for the telephony tests. RSA keys are generated once per session; nothing touches the network."""

from collections.abc import Callable

import pytest

from sparta.config import Settings

from .helpers import SigningKey

TENANT = "11111111-2222-3333-4444-555555555555"
ACS_RESOURCE = "acs-resource-id-for-tests"
EVENT_GRID_AUDIENCE = "api://sparta-event-grid-test"


@pytest.fixture(scope="session")
def key() -> SigningKey:
    return SigningKey("key-1")


@pytest.fixture(scope="session")
def other_key() -> SigningKey:
    return SigningKey("key-1")  # same kid as ``key`` on purpose: a different key claiming to be the trusted one


@pytest.fixture(scope="session")
def rotated_key() -> SigningKey:
    return SigningKey("key-2")


@pytest.fixture(scope="session")
def weak_key() -> SigningKey:
    return SigningKey("key-weak", bits=1024)


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "acs_connection_string": "endpoint=https://acs-test.communication.azure.com/;accesskey=dGVzdA==",
            "acs_callback_base_url": "https://sparta.example.com",
            "acs_resource_id": ACS_RESOURCE,
            "entra_tenant_id": TENANT,
            "event_grid_audience": EVENT_GRID_AUDIENCE,
            "provider_timeout_s": 1.0,
            "provider_max_retries": 1,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return make
