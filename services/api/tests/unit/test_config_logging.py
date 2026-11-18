import json
import logging

import pytest

from sparta.config import ConfigurationError, Environment, Settings
from sparta.logging_setup import (
    JsonFormatter,
    call_id_var,
    correlation_id_var,
    redact_text,
    redact_value,
)


def prod(**overrides) -> dict:
    base = {
        "env": "production",
        "auth_mode": "oidc",
        "oidc_issuer": "https://login.example/",
        "oidc_audience": "api://sparta",
        "data_keys": "k",
        "pepper": "p",
        "webhook_secret": "w",
        "database_url": "postgresql+asyncpg://u:p@db/sparta",
        "redis_url": "redis://r:6379/0",
        "cors_origins": "https://app.example",
        "trusted_hosts": "api.example",
    }
    base.update(overrides)
    return base


def test_production_with_a_complete_configuration_is_accepted():
    s = Settings(**prod(), _env_file=None)
    assert s.is_production and s.cors_origins == ["https://app.example"]


def test_dev_authentication_is_impossible_in_production():
    with pytest.raises(ConfigurationError) as err:
        Settings(**prod(auth_mode="dev"), _env_file=None)
    assert "SPARTA_AUTH_MODE=dev is forbidden" in str(err.value)


def test_every_production_problem_is_reported_at_once_with_actionable_text():
    with pytest.raises(ConfigurationError) as err:
        Settings(env="production", _env_file=None)
    msg = str(err.value)
    for needle in (
        "SPARTA_DATA_KEYS",
        "SPARTA_PEPPER",
        "SPARTA_WEBHOOK_SECRET",
        "PostgreSQL",
        "SPARTA_REDIS_URL",
        "SPARTA_CORS_ORIGINS",
        "SPARTA_TRUSTED_HOSTS",
    ):
        assert needle in msg


def test_wildcard_origins_and_raw_audio_storage_are_refused_in_production():
    with pytest.raises(ConfigurationError) as err:
        Settings(**prod(cors_origins="*", feature_raw_audio_storage=True), _env_file=None)
    assert "no '*'" in str(err.value) and "Raw audio storage" in str(err.value)


def test_production_telephony_that_delivers_audio_needs_a_real_recogniser():
    azure = {"telephony_provider": "azure", "acs_connection_string": "endpoint=x", "acs_callback_base_url": "https://x"}
    with pytest.raises(ConfigurationError, match="SPARTA_STT_PROVIDER=azure"):
        Settings(**prod(**azure), _env_file=None)
    Settings(
        **prod(**azure, stt_provider="azure", azure_speech_key="k", azure_speech_region="centralindia"), _env_file=None
    )


def test_selecting_a_real_provider_requires_its_credentials_in_any_environment():
    s = Settings(telephony_provider="azure", llm_provider="azure_openai", stt_provider="azure", _env_file=None)
    problems = " ".join(s.problems())
    assert (
        "ACS_CONNECTION_STRING" in problems and "AZURE_OPENAI_ENDPOINT" in problems and "AZURE_SPEECH_KEY" in problems
    )


def test_privacy_defaults_are_conservative(monkeypatch):
    monkeypatch.delenv("SPARTA_ENV", raising=False)
    s = Settings(_env_file=None)
    assert s.env is Environment.DEVELOPMENT and s.telephony_provider == "simulator"
    assert not s.feature_raw_audio_storage and not s.feature_personal_voice and not s.feature_llm_summaries


def test_telephony_provider_can_be_selected_with_the_documented_variable(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "other")
    assert Settings(_env_file=None).telephony_provider == "other"


# ------------------------------------------------------------------------------------------------ logging
@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("otp is 482913", "482913"),
        ("call +91 98765 43210 now", "98765"),
        ("mail me at owner@example.com", "owner@example.com"),
        ("Authorization: Bearer abc.def-ghi_jkl123", "abc.def"),
        ("api_key=sk-live-123456789", "sk-live"),
        ("jwt eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhYmMifQ.c2lnbmF0dXJl", "eyJhbGci"),
    ],
)
def test_text_redaction_removes_sensitive_values(raw, must_not_contain):
    assert must_not_contain not in redact_text(raw)


def test_sensitive_field_names_are_redacted_whatever_their_value():
    assert redact_value("transcript", "hello there") == "[redacted]"
    assert redact_value("caller_number", "+919876543210") == "[redacted]"
    assert redact_value("Authorization", "Bearer x") == "[redacted]"
    assert redact_value("password", "hunter2") == "[redacted]"
    assert redact_value("token_count", 12) == 12
    assert redact_value("duration_ms", 42) == 42
    nested = redact_value("meta", {"text": "secret words", "n": 3})
    assert nested == {"text": "[redacted]", "n": 3}


def test_json_log_lines_carry_correlation_ids_and_no_content(caplog):
    logger = logging.getLogger("sparta.test")
    handler = logging.StreamHandler()
    stream = []
    handler.emit = lambda record: stream.append(handler.format(record))  # type: ignore[method-assign]
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    tok1, tok2 = correlation_id_var.set("req-123"), call_id_var.set("call_abc")
    try:
        logger.info("turn processed for +91 98765 43210", extra={"transcript": "my otp is 482913", "stage_ms": 12})
    finally:
        correlation_id_var.reset(tok1)
        call_id_var.reset(tok2)
        logger.removeHandler(handler)
    line = json.loads(stream[0])
    assert line["correlation_id"] == "req-123" and line["call_id"] == "call_abc"
    assert line["transcript"] == "[redacted]" and line["stage_ms"] == 12
    assert "98765" not in stream[0] and "482913" not in stream[0]
