"""Application settings. Everything comes from environment variables (prefix ``SPARTA_``); secrets never live in code.

Production guards fail fast with an actionable message instead of a stack trace.
"""

import importlib.util
import ipaddress
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
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


_BARE_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")
MIN_ASTERISK_SECRET_CHARS = 24


def _peer_problem(entry: str) -> str | None:
    """Why ``entry`` is not an acceptable media peer: an address, a network, or a host. Never (nearly) the whole internet."""
    try:
        network = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        if _BARE_HOST.fullmatch(entry):
            return None
        return f"'{entry}' is neither an IP address, a CIDR range nor a host name"
    if network.prefixlen == 0:
        return f"'{entry}' would allow every address"
    if network.prefixlen < (
        8 if network.version == 4 else 7
    ):  # a private /8 (or an IPv6 ULA /7) is the widest that makes sense
        return f"'{entry}' is far too wide for one PBX: list its address, or the small network it sits on"
    return None


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


_VOICE_ENTRY = re.compile(r"([A-Za-z]{2,3})-([A-Za-z0-9]{2,8})=([A-Za-z0-9][A-Za-z0-9_.-]{0,63})")


def _voice_map(entries: list[str]) -> tuple[dict[str, str], list[str]]:
    """``locale=voice_id`` entries as ``{"en-IN": voice_id}`` and the entries that are malformed or repeat a locale."""
    voices: dict[str, str] = {}
    bad: list[str] = []
    for entry in entries:
        match = _VOICE_ENTRY.fullmatch(entry.strip())
        if match is None:
            bad.append(entry)
            continue
        locale = f"{match.group(1).lower()}-{match.group(2).upper() if len(match.group(2)) == 2 else match.group(2)}"
        if locale in voices:
            bad.append(entry)
        else:
            voices[locale] = match.group(3)
    return voices, bad


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
        "exposes the owner API of a development-identity server. Needs SPARTA_TRUSTED_HOSTS to list explicit host names "
        "(a listed host name is matched exactly, so every other Host header must be refused by trusted hosts). Not a "
        "substitute for sign-in in production.",
    )
    public_base_url: str = "http://localhost:8000"
    max_request_bytes: int = 512_000
    max_audio_bytes: int = 8_000_000
    max_audio_seconds: int = 120
    expose_metrics: bool = False

    # --- providers (selected by configuration) --------------------------------------
    telephony_provider: Literal["simulator", "azure", "twilio", "asterisk", "other"] = Field(
        default="simulator",
        validation_alias=AliasChoices("TELEPHONY_PROVIDER", "SPARTA_TELEPHONY_PROVIDER"),
    )
    stt_provider: Literal["simulator", "azure", "local", "fake"] = "simulator"
    tts_provider: Literal["simulator", "azure", "local", "fake"] = "simulator"
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
    azure_openai_output_limit_param: Literal["auto", "max_tokens", "max_completion_tokens"] = Field(
        default="auto",
        description="Name of the output-limit parameter the deployment accepts. GPT-4-class deployments take "
        "max_tokens, reasoning-model deployments take max_completion_tokens; 'auto' starts with max_tokens and "
        "switches (once, remembered) when the service reports it as unsupported.",
    )
    azure_openai_send_temperature: bool = Field(
        default=True,
        description="Send temperature=0. Reasoning-model deployments reject it: 'auto' handling drops it after the "
        "first rejection, or set this to false.",
    )
    acs_connection_string: SecretStr | None = None
    acs_callback_base_url: str | None = None
    acs_resource_id: str | None = Field(
        default=None, description="ACS resource id; the expected audience of Call Automation callback JWTs"
    )
    entra_tenant_id: str | None = Field(default=None, description="Tenant that issues Event Grid delivery tokens")
    event_grid_audience: str | None = Field(default=None, description="Audience of Event Grid secure-webhook tokens")
    event_grid_allowed_app_ids: str | None = Field(
        default=None,
        description="Comma-separated application ids (the appid/azp claim) allowed to deliver Event Grid events: the "
        "Microsoft.EventGrid application of your cloud. The role alone does not prove the caller, because the "
        "subscription-writer app holds it too.",
    )
    twilio_account_sid: str | None = Field(
        default=None, description="Twilio account SID (AC followed by 32 hex digits)"
    )
    twilio_auth_token: SecretStr | None = Field(
        default=None, description="Twilio auth token: signs webhooks, authenticates the REST API, keys stream tokens"
    )
    twilio_callback_base_url: str | None = Field(
        default=None, description="Public https origin Twilio calls (the voice webhook) and streams audio to"
    )
    twilio_caller_id: str | None = Field(
        default=None,
        description="E.164 Twilio number shown to the owner on a takeover; defaults to the number the caller dialled",
    )
    twilio_verify_media_signature: bool = Field(
        default=True,
        description="Require Twilio's X-Twilio-Signature on the media WebSocket upgrade (the per-call token in the "
        "start message is always required). Switch off only to debug a signature mismatch, never in production.",
    )
    provider_timeout_s: float = 6.0
    provider_max_retries: int = 2
    simulator_enabled: bool = True

    # --- local SIP: Asterisk (no PSTN) ---------------------------------------------
    asterisk_media_bind: str = Field(
        default="127.0.0.1",
        description="Address of the AudioSocket listener Asterisk connects to for each call. Use 0.0.0.0 only inside a "
        "container network and keep SPARTA_ASTERISK_MEDIA_PEERS tight.",
    )
    asterisk_media_port: int = Field(default=8090, ge=0, le=65535, description="0 picks any free port (tests)")
    asterisk_media_peers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description="Peers allowed to open a media connection: IP addresses, CIDR ranges or host names (resolved when a "
        "connection arrives; 'asterisk' in Docker Compose). Anything else is dropped before a byte is read.",
    )
    asterisk_webhook_secret: SecretStr | None = Field(
        default=None,
        description="Shared secret of the dialplan callbacks (HTTP Basic password). At least 24 random characters.",
    )
    asterisk_webhook_secret_file: str | None = Field(
        default=None, description="Read the callback secret from this file instead (a mounted secret)"
    )
    asterisk_extension: str = Field(
        default="6000", pattern=r"^[0-9]{2,8}$", description="Extension that reaches Sparta"
    )
    asterisk_owner_extension: str = Field(
        default="6002", pattern=r"^[0-9]{2,8}$", description="Extension rung on Take Over (a SIP phone, never PSTN)"
    )
    asterisk_sip_host: str = Field(default="127.0.0.1", description="Where `sparta doctor` probes Asterisk's SIP port")
    asterisk_sip_port: int = Field(default=5060, ge=1, le=65535)
    asterisk_claim_ttl_s: float = Field(
        default=10.0, gt=0, description="Seconds an issued media id stays valid before Asterisk must have used it"
    )
    asterisk_handshake_timeout_s: float = Field(default=3.0, gt=0)
    asterisk_idle_timeout_s: float = Field(
        default=10.0, gt=0, description="A media connection that sends nothing for this long is closed"
    )
    asterisk_playback_lead_ms: int = Field(
        default=40,
        ge=0,
        le=200,
        description="How far ahead of real time speech is sent. A stop cannot recall this much audio, so keep it small",
    )
    asterisk_max_media_connections: int = Field(default=8, ge=1, le=64)
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

    # --- local speech: free, open-source, on this machine (optional extra `sparta-api[local-speech]`) ------------------
    local_model_dir: str = Field(
        default="./var/models",
        description="Where `python -m sparta models fetch` puts the speech models. The providers only read from here and "
        "never download anything themselves.",
    )
    local_stt_model: str = Field(
        default="small",
        description="faster-whisper model: a name from `python -m sparta models list` (small, large-v3-turbo) or the "
        "path of an existing CTranslate2 model directory",
    )
    local_stt_device: Literal["cpu", "cuda", "auto"] = "cpu"
    local_stt_compute_type: str = Field(default="int8", description="CTranslate2 quantisation, e.g. int8, int8_float16")
    local_stt_cpu_threads: int = Field(default=4, ge=1, le=32)
    local_tts_voices: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "en-IN=en_US-ljspeech-medium",
            "hi-IN=hi_IN-priyamvada-medium",
            "kn-IN=kn_IN-syspin_male-medium",
        ],
        description="Piper voice per locale, comma separated `locale=voice_id`. A locale without an installed voice is "
        "refused, never spoken in another language.",
    )
    local_tts_fallback_locale: str | None = Field(
        default="en-IN",
        description="Reserved for a labelled English fallback: it is used only when a speech request carries an English "
        "rendering, which it does not yet, so today a locale without a voice is always refused. Blank disables it.",
    )
    local_max_concurrent_inference: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Recognitions (and, separately, syntheses) running at once. Each uses SPARTA_LOCAL_STT_CPU_THREADS "
        "cores, so raise it only on a machine with cores to spare.",
    )

    # --- limits and guardrails -----------------------------------------------------
    rate_limit_per_minute: int = 240
    call_create_rate_limit_per_minute: int = 20
    profile_write_rate_limit_per_minute: int = 12  # assistant-profile saves (a new owner name builds matchers)
    daily_call_cap: int = 200
    daily_call_minutes_cap: float = Field(
        default=240.0,
        ge=0,
        description="Minutes of real (not simulated) calls per owner per UTC day; further calls are rejected. 0 = off",
    )
    per_number_daily_call_cap: int = Field(
        default=10,
        ge=0,
        description="Real calls accepted from one caller number per owner per UTC day; further calls are rejected "
        "without being answered. 0 = off",
    )
    daily_screening_event_cap: int = 2000  # native Android screening events per owner per UTC day
    max_call_duration_s: int = 600
    abandoned_call_timeout_s: int = 180
    provider_failure_limit: int = Field(
        default=2,
        ge=0,
        description="Consecutive failures of speaking or listening after which a real call is ended with a summary "
        "that says Sparta could not screen it. 0 = never end a call for that",
    )
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
        "cors_origins",
        "allowed_ws_origins",
        "trusted_hosts",
        "provider_only_hosts",
        "oidc_algorithms",
        "asterisk_media_peers",
        "local_tts_voices",
        mode="before",
    )
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("local_tts_fallback_locale", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def local_tts_voice_map(self) -> dict[str, str]:
        """``local_tts_voices`` as ``{locale: voice_id}`` (malformed entries are left out; ``problems()`` reports them)."""
        return _voice_map(self.local_tts_voices)[0]

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def telephony_kind(self) -> Literal["simulator", "azure", "asterisk", "other"]:
        """The provider kind the API contract knows: Twilio is reported as the generic ``other`` kind."""
        return "other" if self.telephony_provider == "twilio" else self.telephony_provider

    def asterisk_secret(self) -> str | None:
        """The dialplan callback secret: the value, else the first line of the mounted secret file."""
        if self.asterisk_webhook_secret is not None:
            return self.asterisk_webhook_secret.get_secret_value().strip() or None
        if self.asterisk_webhook_secret_file:
            try:
                with open(self.asterisk_webhook_secret_file, encoding="utf-8") as handle:
                    return handle.readline().strip() or None
            except OSError:
                return None
        return None

    @property
    def ws_origins(self) -> list[str]:
        return self.allowed_ws_origins or self.cors_origins

    def _local_speech_problems(self) -> list[str]:
        """Why ``SPARTA_STT_PROVIDER=local`` / ``SPARTA_TTS_PROVIDER=local`` cannot work with this configuration."""
        out: list[str] = []
        install = "pip install 'sparta-api[local-speech]'"
        if self.stt_provider == "local":
            if not _module_available("faster_whisper"):
                out.append(f"SPARTA_STT_PROVIDER=local requires the faster-whisper package ({install})")
            from sparta.providers.local_models import STT_MODELS

            model = self.local_stt_model.strip()
            if model not in STT_MODELS and not (model and Path(model).expanduser().is_dir()):
                out.append(
                    f"SPARTA_LOCAL_STT_MODEL must be one of {', '.join(STT_MODELS)} or the path of an existing "
                    f"CTranslate2 model directory, got '{model[:60]}'"
                )
        if self.tts_provider == "local":
            if not _module_available("piper"):
                out.append(f"SPARTA_TTS_PROVIDER=local requires the piper-tts package ({install})")
            voices, bad = _voice_map(self.local_tts_voices)
            out.extend(
                f"SPARTA_LOCAL_TTS_VOICES entry '{entry[:60]}' must look like 'en-IN=en_US-ljspeech-medium' and name "
                "each locale once"
                for entry in bad
            )
            if not voices:
                out.append("SPARTA_LOCAL_TTS_VOICES must name at least one 'locale=voice_id' entry")
        return out

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
        if self.telephony_provider == "twilio" and not (
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_callback_base_url
        ):
            out.append(
                "TELEPHONY_PROVIDER=twilio requires SPARTA_TWILIO_ACCOUNT_SID, SPARTA_TWILIO_AUTH_TOKEN and "
                "SPARTA_TWILIO_CALLBACK_BASE_URL"
            )
        if self.telephony_provider == "other" and not self.telephony_plugin:
            out.append("TELEPHONY_PROVIDER=other requires SPARTA_TELEPHONY_PLUGIN='package.module:factory'")
        if self.telephony_provider == "asterisk":
            secret = self.asterisk_secret()
            if not secret:
                out.append(
                    "TELEPHONY_PROVIDER=asterisk requires SPARTA_ASTERISK_WEBHOOK_SECRET (or "
                    "SPARTA_ASTERISK_WEBHOOK_SECRET_FILE): the dialplan callbacks must be authenticated"
                )
            elif len(secret) < MIN_ASTERISK_SECRET_CHARS:
                out.append(f"The Asterisk callback secret must be at least {MIN_ASTERISK_SECRET_CHARS} characters")
            out.extend(
                f"SPARTA_ASTERISK_MEDIA_PEERS: {why}" for why in map(_peer_problem, self.asterisk_media_peers) if why
            )
            if not self.asterisk_media_peers:
                out.append("SPARTA_ASTERISK_MEDIA_PEERS must list at least one peer (Asterisk's address or host name)")
            if self.asterisk_extension == self.asterisk_owner_extension:
                out.append("SPARTA_ASTERISK_EXTENSION and SPARTA_ASTERISK_OWNER_EXTENSION must differ")
        if self.provider_only_hosts:
            if not all(_BARE_HOST.fullmatch(host) for host in self.provider_only_hosts):
                out.append(
                    "SPARTA_PROVIDER_ONLY_HOSTS lists bare host names (no scheme, port or path), "
                    "for example 'abc-8000.devtunnels.ms'"
                )
            if "*" in self.trusted_hosts:
                # The guard only recognises the listed names; trusted hosts is what rejects every other Host header.
                out.append(
                    "SPARTA_PROVIDER_ONLY_HOSTS requires SPARTA_TRUSTED_HOSTS to list explicit host names (the tunnel "
                    "host and localhost): with '*' any other Host header (an alias of the tunnel, say) would reach "
                    "the whole owner API"
                )
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
        out.extend(self._local_speech_problems())
        if self.llm_provider == "azure_openai" and not (
            self.azure_openai_endpoint and self.azure_openai_key and self.azure_openai_deployment
        ):
            out.append(
                "SPARTA_LLM_PROVIDER=azure_openai requires SPARTA_AZURE_OPENAI_ENDPOINT, "
                "SPARTA_AZURE_OPENAI_KEY and SPARTA_AZURE_OPENAI_DEPLOYMENT"
            )
        if self.is_production:
            if "fake" in (self.stt_provider, self.tts_provider):
                out.append(
                    "SPARTA_STT_PROVIDER=fake and SPARTA_TTS_PROVIDER=fake are test-only (they recognise and speak "
                    "nothing real): forbidden when SPARTA_ENV=production"
                )
            if self.telephony_provider in ("azure", "twilio", "asterisk") and self.stt_provider in (
                "simulator",
                "fake",
            ):
                out.append(
                    f"TELEPHONY_PROVIDER={self.telephony_provider} delivers the caller's audio, which needs speech "
                    "recognition: set SPARTA_STT_PROVIDER=azure (or local)"
                )
            if self.telephony_provider in ("azure", "twilio", "asterisk") and self.tts_provider in (
                "simulator",
                "fake",
            ):
                out.append(
                    f"TELEPHONY_PROVIDER={self.telephony_provider} speaks to the caller, which needs speech "
                    "synthesis: set SPARTA_TTS_PROVIDER=azure (or local)"
                )
            if self.telephony_provider == "twilio" and not self.twilio_verify_media_signature:
                out.append(
                    "SPARTA_TWILIO_VERIFY_MEDIA_SIGNATURE=false is a debugging switch: it is forbidden when "
                    "SPARTA_ENV=production (reproduce the mismatch on a development tunnel instead)"
                )
            if self.telephony_provider == "azure" and not (self.event_grid_allowed_app_ids or "").strip():
                out.append(
                    "TELEPHONY_PROVIDER=azure requires SPARTA_EVENT_GRID_ALLOWED_APP_IDS in production: the Event "
                    "Grid role alone does not show who delivered an IncomingCall event"
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
