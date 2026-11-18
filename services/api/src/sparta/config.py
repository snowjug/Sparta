"""Application settings. Everything comes from environment variables (prefix ``SPARTA_``); secrets never live in code.

Production guards fail fast with an actionable message instead of a stack trace.
"""

import importlib.util
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ConfigurationError(RuntimeError):
    """Raised at startup when configuration is unsafe or incomplete. The message lists every problem."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("Invalid Sparta configuration:\n  - " + "\n  - ".join(problems))


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _module_available(name: str) -> bool:
    """Whether ``name`` can be imported, without importing it (a missing parent package counts as unavailable)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPARTA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- runtime -------------------------------------------------------------------
    env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True
    service_name: str = "sparta-api"
    data_dir: str = "./var"

    # --- authentication ------------------------------------------------------------
    auth_mode: Literal["dev", "oidc"] = "dev"
    allow_network_dev_auth: bool = Field(
        default=False,
        description="Let `sparta serve` listen on a non-loopback address while the development identity is active "
        "(anyone who can reach the server acts as the owner). Only for a trusted local network or container.",
    )
    dev_user_id: str = "dev-owner"
    dev_user_name: str = "Atharv"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["RS256"])

    # --- storage -------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./var/sparta.db"
    redis_url: str | None = None
    data_keys: SecretStr | None = Field(
        default=None, description="Comma-separated Fernet keys; the first encrypts, all decrypt (rotation)."
    )
    pepper: SecretStr | None = Field(default=None, description="HMAC pepper for caller-number hashing")
    webhook_secret: SecretStr | None = None
    auto_migrate: bool = Field(default=True, description="Run Alembic migrations at startup outside production")

    # --- HTTP surface --------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    allowed_ws_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trusted_hosts: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    provider_only_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Host names that may only reach the health probes and the provider callback and media routes "
        "(a development tunnel, for instance). Every other route answers 404 on those hosts, so a public tunnel never "
        "exposes the owner API of a development-identity server. Not a substitute for sign-in in production.",
    )
    public_base_url: str = "http://localhost:8000"
    max_request_bytes: int = 512_000
    max_audio_bytes: int = 8_000_000
    max_audio_seconds: int = 120
    expose_metrics: bool = False

    # --- providers (selected by configuration) --------------------------------------
    telephony_provider: Literal["simulator", "azure", "other"] = Field(
        default="simulator",
        validation_alias=AliasChoices("TELEPHONY_PROVIDER", "SPARTA_TELEPHONY_PROVIDER"),
    )
    stt_provider: Literal["simulator", "azure"] = "simulator"
    tts_provider: Literal["simulator", "azure"] = "simulator"
    llm_provider: Literal["rules", "azure_openai"] = "rules"

    azure_speech_key: SecretStr | None = None
    azure_speech_region: str | None = None
    azure_speech_endpoint: str | None = Field(
        default=None, description="Custom-domain Speech endpoint; defaults to the regional host"
    )
    azure_speech_streaming: Literal["auto", "on", "off"] = Field(
        default="auto",
        description="Live recognition through the Speech SDK (partial transcripts, lower latency): 'auto' uses it when "
        "the SDK is installed and falls back to one REST request per utterance otherwise; 'on' requires the SDK; "
        "'off' always uses REST.",
    )
    azure_openai_endpoint: str | None = None
    azure_openai_key: SecretStr | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    acs_connection_string: SecretStr | None = None
    acs_callback_base_url: str | None = None
    acs_resource_id: str | None = Field(
        default=None, description="ACS resource id; the expected audience of Call Automation callback JWTs"
    )
    entra_tenant_id: str | None = Field(default=None, description="Tenant that issues Event Grid delivery tokens")
    event_grid_audience: str | None = Field(default=None, description="Audience of Event Grid secure-webhook tokens")
    provider_timeout_s: float = 6.0
    provider_max_retries: int = 2
    simulator_enabled: bool = True
    telephony_plugin: str | None = Field(
        default=None,
        description="With TELEPHONY_PROVIDER=other: 'package.module:factory' returning a TelephonyProvider",
    )
    max_active_calls: int = 5
    telephony_owner_user_id: str | None = Field(
        default=None, description="Owner that receives calls delivered by a real telephony provider"
    )
    forwarding_number: str | None = Field(
        default=None,
        description="Number the owner forwards unanswered/unknown calls to (the provider's inbound number)",
    )
    estimated_stt_per_audio_hour_usd: float = 0.0
    estimated_tts_per_million_chars_usd: float = 0.0
    estimated_llm_per_million_prompt_tokens_usd: float = 0.0
    estimated_llm_per_million_completion_tokens_usd: float = 0.0
    estimated_telephony_per_minute_usd: float = 0.0

    # --- limits and guardrails -----------------------------------------------------
    rate_limit_per_minute: int = 240
    call_create_rate_limit_per_minute: int = 20
    profile_write_rate_limit_per_minute: int = 12  # assistant-profile saves (a new owner name builds matchers)
    daily_call_cap: int = 200
    daily_screening_event_cap: int = 2000  # native Android screening events per owner per UTC day
    max_call_duration_s: int = 600
    abandoned_call_timeout_s: int = 180
    reaper_interval_s: float = 15.0
    retention_job_interval_s: float = 3600.0
    escalation_resolver_interval_s: float = 5.0

    # --- feature flags (expensive or sensitive features are off by default) ---------
    feature_personal_voice: bool = False
    feature_llm_summaries: bool = False
    feature_raw_audio_storage: bool = False

    # --- observability -------------------------------------------------------------
    otel_enabled: bool = True
    otlp_endpoint: str | None = None

    @field_validator(
        "cors_origins", "allowed_ws_origins", "trusted_hosts", "provider_only_hosts", "oidc_algorithms", mode="before"
    )
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def ws_origins(self) -> list[str]:
        return self.allowed_ws_origins or self.cors_origins

    def problems(self) -> list[str]:
        """Every reason this configuration is unsafe or incomplete for the selected environment."""
        out: list[str] = []
        if self.auth_mode == "oidc":
            if not self.oidc_issuer:
                out.append("SPARTA_OIDC_ISSUER is required when SPARTA_AUTH_MODE=oidc")
            if not self.oidc_audience:
                out.append("SPARTA_OIDC_AUDIENCE is required when SPARTA_AUTH_MODE=oidc")
            if not (self.oidc_jwks_url or self.oidc_issuer):
                out.append("SPARTA_OIDC_JWKS_URL (or an issuer to derive it from) is required for OIDC")
        if self.telephony_provider == "azure" and not (self.acs_connection_string and self.acs_callback_base_url):
            out.append(
                "TELEPHONY_PROVIDER=azure requires SPARTA_ACS_CONNECTION_STRING and SPARTA_ACS_CALLBACK_BASE_URL"
            )
        if self.telephony_provider == "other" and not self.telephony_plugin:
            out.append("TELEPHONY_PROVIDER=other requires SPARTA_TELEPHONY_PLUGIN='package.module:factory'")
        if self.stt_provider == "azure" and not (self.azure_speech_key and self.azure_speech_region):
            out.append("SPARTA_STT_PROVIDER=azure requires SPARTA_AZURE_SPEECH_KEY and SPARTA_AZURE_SPEECH_REGION")
        if self.tts_provider == "azure" and not (self.azure_speech_key and self.azure_speech_region):
            out.append("SPARTA_TTS_PROVIDER=azure requires SPARTA_AZURE_SPEECH_KEY and SPARTA_AZURE_SPEECH_REGION")
        if (
            self.stt_provider == "azure"
            and self.azure_speech_streaming == "on"
            and not _module_available("azure.cognitiveservices.speech")
        ):
            out.append(
                "SPARTA_AZURE_SPEECH_STREAMING=on requires the azure-cognitiveservices-speech package "
                "(pip install 'sparta-api[azure]'); use 'auto' to fall back to per-utterance recognition"
            )
        if self.llm_provider == "azure_openai" and not (
            self.azure_openai_endpoint and self.azure_openai_key and self.azure_openai_deployment
        ):
            out.append(
                "SPARTA_LLM_PROVIDER=azure_openai requires SPARTA_AZURE_OPENAI_ENDPOINT, "
                "SPARTA_AZURE_OPENAI_KEY and SPARTA_AZURE_OPENAI_DEPLOYMENT"
            )
        if self.is_production:
            if self.telephony_provider == "azure" and self.stt_provider == "simulator":
                out.append(
                    "TELEPHONY_PROVIDER=azure delivers the caller's audio, which needs speech recognition: "
                    "set SPARTA_STT_PROVIDER=azure"
                )
            if self.auth_mode == "dev":
                out.append("SPARTA_AUTH_MODE=dev is forbidden when SPARTA_ENV=production (use oidc)")
            if not self.data_keys:
                out.append("SPARTA_DATA_KEYS (Fernet key list) is required in production")
            if not self.pepper:
                out.append("SPARTA_PEPPER is required in production")
            if not self.webhook_secret:
                out.append("SPARTA_WEBHOOK_SECRET is required in production")
            if self.database_url.startswith("sqlite"):
                out.append("SQLite is not allowed in production; set SPARTA_DATABASE_URL to PostgreSQL")
            if not self.redis_url:
                out.append("SPARTA_REDIS_URL is required in production for shared rate limits and call coordination")
            if "*" in self.cors_origins:
                out.append("SPARTA_CORS_ORIGINS must list explicit origins in production (no '*')")
            elif any(not o.startswith("https://") or "localhost" in o or "127.0.0.1" in o for o in self.cors_origins):
                out.append("SPARTA_CORS_ORIGINS must be https origins and may not include localhost in production")
            if "*" in self.trusted_hosts:
                out.append("SPARTA_TRUSTED_HOSTS must list explicit hostnames in production (no '*')")
            if self.feature_raw_audio_storage:
                out.append("Raw audio storage is not permitted in production builds of this release")
        return out

    @model_validator(mode="after")
    def _enforce(self) -> "Settings":
        if self.env is Environment.PRODUCTION:
            problems = self.problems()
            if problems:
                raise ConfigurationError(problems)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
