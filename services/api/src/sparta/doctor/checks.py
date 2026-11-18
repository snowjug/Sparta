"""Offline checks for ``sparta doctor``: what the configuration says, without touching the network.

Every function returns a list of :class:`Check`. None of them reads a secret into a message: a secret is either
"configured", "missing" or "malformed" (with the format that is expected, never the value that was found).
"""

import base64
import binascii
import importlib.metadata
import ipaddress
import re
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from sparta.config import Environment, Settings
from sparta.doctor.model import Check, Status
from sparta.language.registry import load_registry
from sparta.providers.azure_common import https_origin, valid_region
from sparta.providers.tts.catalog import DEFAULT_VOICES, is_known_voice
from sparta.services.numbers import mask_number

CORE = "Core"
ACS = "Azure Communication Services (telephony)"
TWILIO = "Twilio (telephony)"
SPEECH = "Azure Speech"
OPENAI = "Azure OpenAI"
LIMITS = "Limits and estimated cost"

_E164 = re.compile(r"\+[1-9][0-9]{6,14}")
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ACS_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.communication\.azure\.com", re.IGNORECASE)
_TWILIO_SID = re.compile(r"AC[0-9a-f]{32}")
_TWILIO_TOKEN = re.compile(r"[0-9a-f]{32}")
_API_VERSION = re.compile(r"\d{4}-\d{2}-\d{2}(?:-preview)?")

# Assumptions behind the diagnostic cost estimate (stated in its output; it is not a bill).
ASSUMED_ASSISTANT_CHARS_PER_MINUTE = 450
ASSUMED_LLM_TURNS_PER_MINUTE = 6
ASSUMED_LLM_PROMPT_TOKENS_PER_TURN = 600
ASSUMED_LLM_COMPLETION_TOKENS_PER_TURN = 80


def _check(id_: str, group: str, title: str, status: Status, detail: str = "", fix: str = "") -> Check:
    return Check(id_, group, title, status, detail, fix)


def callback_base(settings: Settings, override: str | None = None) -> str | None:
    """The configured public origin of whichever telephony provider is selected (or the override)."""
    if override:
        return override
    return (
        settings.twilio_callback_base_url if settings.telephony_provider == "twilio" else settings.acs_callback_base_url
    )


def callback_host(settings: Settings, override: str | None = None) -> str | None:
    origin = https_origin(callback_base(settings, override))
    return urlsplit(origin).hostname if origin else None


def is_public_host(host: str | None) -> bool:
    """False for loopback, private, link-local and single-label hosts: a provider on the internet cannot reach them."""
    if not host:
        return False
    lowered = host.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return "." in lowered
    return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)


# ------------------------------------------------------------------------------------------------------- core
def core_checks(settings: Settings, *, callback_url: str | None = None) -> list[Check]:
    out: list[Check] = []
    production = settings.env is Environment.PRODUCTION
    out.append(
        _check(
            "core.environment",
            CORE,
            "Environment",
            Status.PASS if production else Status.WARNING,
            f"SPARTA_ENV={settings.env.value}",
            ""
            if production
            else "Real calls belong in SPARTA_ENV=production: development allows the development "
            "identity, SQLite and in-process state, none of which is safe on a public URL.",
        )
    )
    out.append(_auth_check(settings, callback_url))
    out.extend(_encryption_checks(settings))
    out.append(_database_config(settings, production))
    out.append(_redis_config(settings, production))
    out.extend(_http_surface(settings, production, callback_url))
    if production:
        out.extend(
            _check(
                f"core.startup.{index}",
                CORE,
                "The server would refuse to start",
                Status.BLOCKED,
                problem,
                "Fix this setting; `sparta serve` refuses to run in production until every problem is gone.",
            )
            for index, problem in enumerate(settings.problems(), start=1)
        )
    return out


def _auth_check(settings: Settings, callback_url: str | None) -> Check:
    if settings.auth_mode == "oidc":
        missing = [
            name
            for name, value in (
                ("SPARTA_OIDC_ISSUER", settings.oidc_issuer),
                ("SPARTA_OIDC_AUDIENCE", settings.oidc_audience),
            )
            if not value
        ]
        if not (settings.oidc_jwks_url or settings.oidc_issuer):
            missing.append("SPARTA_OIDC_JWKS_URL")
        if missing:
            return _check(
                "core.auth",
                CORE,
                "Sign-in (OpenID Connect)",
                Status.BLOCKED,
                "missing: " + ", ".join(missing),
                "Set the issuer and audience of your identity provider (docs/DEPLOYMENT.md, 'Authentication').",
            )
        return _check(
            "core.auth",
            CORE,
            "Sign-in (OpenID Connect)",
            Status.UNVERIFIED,
            "OIDC is configured but has never been tried against a real identity provider by this project.",
            "Sign in once through the web app with a real account and call GET /api/v1/me.",
        )
    host = callback_host(settings, callback_url)
    if host and is_public_host(host) and host not in settings.provider_only_hosts:
        return _check(
            "core.auth",
            CORE,
            "Sign-in (development identity on a public URL)",
            Status.BLOCKED,
            "SPARTA_AUTH_MODE=dev has no sign-in: anyone who can reach the public callback URL would act as the owner "
            "and could read call history.",
            "Use SPARTA_AUTH_MODE=oidc, or list the public host in SPARTA_PROVIDER_ONLY_HOSTS so that host only serves "
            "provider callbacks (never for production).",
        )
    return _check(
        "core.auth",
        CORE,
        "Sign-in (development identity)",
        Status.WARNING,
        "SPARTA_AUTH_MODE=dev: no sign-in. Acceptable on localhost only.",
        "Use SPARTA_AUTH_MODE=oidc for anything reachable from the internet.",
    )


def _encryption_checks(settings: Settings) -> list[Check]:
    out: list[Check] = []
    keys = settings.data_keys.get_secret_value().split(",") if settings.data_keys else []
    if not keys:
        out.append(
            _check(
                "core.data_keys",
                CORE,
                "Content encryption keys (SPARTA_DATA_KEYS)",
                Status.BLOCKED if settings.is_production else Status.WARNING,
                "not set: development keys are generated into the data directory.",
                "Run `python -m sparta keygen` and store the result in Key Vault (never in the repository).",
            )
        )
    else:
        try:
            for key in keys:
                Fernet(key.strip().encode())
        except (ValueError, binascii.Error):
            out.append(
                _check(
                    "core.data_keys",
                    CORE,
                    "Content encryption keys (SPARTA_DATA_KEYS)",
                    Status.BLOCKED,
                    "malformed: expected comma-separated Fernet keys (44 URL-safe base64 characters each).",
                    "Generate a valid key with `python -m sparta keygen`.",
                )
            )
        else:
            out.append(
                _check(
                    "core.data_keys",
                    CORE,
                    "Content encryption keys (SPARTA_DATA_KEYS)",
                    Status.PASS,
                    f"configured and well-formed ({len(keys)} key(s); the first encrypts, all decrypt).",
                )
            )
    out.append(
        _secret_presence("core.pepper", "Caller-number pepper (SPARTA_PEPPER)", settings.pepper, settings.is_production)
    )
    out.append(
        _secret_presence(
            "core.webhook_secret",
            "Webhook secret (SPARTA_WEBHOOK_SECRET)",
            settings.webhook_secret,
            settings.is_production,
        )
    )
    return out


def _secret_presence(id_: str, title: str, value: object, production: bool) -> Check:
    if value is None:
        return _check(
            id_,
            CORE,
            title,
            Status.BLOCKED if production else Status.WARNING,
            "missing.",
            "Run `python -m sparta keygen` for a fresh value.",
        )
    return _check(id_, CORE, title, Status.PASS, "configured.")


def _database_config(settings: Settings, production: bool) -> Check:
    if settings.database_url.startswith("sqlite"):
        return _check(
            "core.database",
            CORE,
            "Database",
            Status.BLOCKED if production else Status.WARNING,
            "SQLite: one process, one file.",
            "Set SPARTA_DATABASE_URL to PostgreSQL (postgresql+asyncpg://...) for a deployment.",
        )
    return _check("core.database", CORE, "Database", Status.PASS, "PostgreSQL URL configured.")


def _redis_config(settings: Settings, production: bool) -> Check:
    if not settings.redis_url:
        return _check(
            "core.redis",
            CORE,
            "Redis (shared state)",
            Status.BLOCKED if production else Status.WARNING,
            "not set: rate limits, webhook replay protection, call locks and WebSocket tickets live in this process "
            "only, which is wrong as soon as there is a second instance or a restart during a call.",
            "Set SPARTA_REDIS_URL (rediss:// with TLS for Azure Cache for Redis).",
        )
    return _check("core.redis", CORE, "Redis (shared state)", Status.PASS, "configured.")


def _http_surface(settings: Settings, production: bool, callback_url: str | None) -> list[Check]:
    out: list[Check] = []
    host = callback_host(settings, callback_url)
    hosts = settings.trusted_hosts
    if "*" in hosts:
        out.append(
            _check(
                "http.trusted_hosts",
                CORE,
                "Trusted hosts",
                Status.BLOCKED if production else Status.WARNING,
                "SPARTA_TRUSTED_HOSTS is a wildcard.",
                "List the API's public host name (and the container probe host) explicitly.",
            )
        )
    elif host and host.lower() not in {h.lower() for h in hosts}:
        out.append(
            _check(
                "http.trusted_hosts",
                CORE,
                "Trusted hosts",
                Status.BLOCKED,
                "the callback host is not in SPARTA_TRUSTED_HOSTS: the provider's requests would be answered with 400.",
                "Add the callback host name to SPARTA_TRUSTED_HOSTS.",
            )
        )
    else:
        out.append(_check("http.trusted_hosts", CORE, "Trusted hosts", Status.PASS, "explicit list."))
    if "*" in settings.cors_origins:
        out.append(
            _check(
                "http.cors",
                CORE,
                "CORS origins",
                Status.BLOCKED,
                "SPARTA_CORS_ORIGINS contains '*'.",
                "List the web app's exact https origin.",
            )
        )
    elif production and any(not o.startswith("https://") for o in settings.cors_origins):
        out.append(
            _check(
                "http.cors",
                CORE,
                "CORS origins",
                Status.BLOCKED,
                "a CORS origin is not https.",
                "Use https origins only.",
            )
        )
    else:
        out.append(_check("http.cors", CORE, "CORS origins", Status.PASS, "explicit origins."))
    return out


# ----------------------------------------------------------------------------------------------- provider selection
def selection_check(settings: Settings, telephony: str = "azure") -> Check:
    chosen = {
        "telephony": settings.telephony_provider,
        "speech recognition": settings.stt_provider,
        "speech synthesis": settings.tts_provider,
    }
    simulated = [name for name, value in chosen.items() if value == "simulator"]
    if len(simulated) == len(chosen):
        return _check(
            "provider.selection",
            CORE,
            "Providers selected",
            Status.BLOCKED,
            "telephony, speech recognition and speech synthesis are all the simulator: no real call can reach Sparta.",
            f"Set SPARTA_TELEPHONY_PROVIDER={telephony}, SPARTA_STT_PROVIDER=azure and SPARTA_TTS_PROVIDER=azure.",
        )
    if simulated:
        return _check(
            "provider.selection",
            CORE,
            "Providers selected",
            Status.BLOCKED,
            "still the simulator: " + ", ".join(simulated) + ". A real call would be deaf or silent.",
            "Select the real provider for every stage a live call passes through.",
        )
    if settings.telephony_provider != telephony:
        return _check(
            "provider.selection",
            CORE,
            "Providers selected",
            Status.BLOCKED,
            f"SPARTA_TELEPHONY_PROVIDER is {settings.telephony_provider!r}, but this check is for {telephony!r}.",
            f"Set SPARTA_TELEPHONY_PROVIDER={telephony}, or run `sparta doctor --provider "
            f"{settings.telephony_provider}`.",
        )
    return _check(
        "provider.selection",
        CORE,
        "Providers selected",
        Status.PASS,
        f"telephony ({telephony}), speech recognition and speech synthesis are real providers.",
    )


# ---------------------------------------------------------------------------------------------------- speech
def speech_checks(settings: Settings) -> list[Check]:
    out: list[Check] = []
    problems: list[str] = []
    if not settings.azure_speech_key:
        problems.append("SPARTA_AZURE_SPEECH_KEY is missing")
    if settings.azure_speech_endpoint:
        if https_origin(settings.azure_speech_endpoint) is None:
            problems.append("SPARTA_AZURE_SPEECH_ENDPOINT must be an https URL")
    elif not settings.azure_speech_region:
        problems.append("SPARTA_AZURE_SPEECH_REGION (or SPARTA_AZURE_SPEECH_ENDPOINT) is missing")
    elif valid_region(settings.azure_speech_region) is None:
        problems.append("SPARTA_AZURE_SPEECH_REGION is malformed (a lower-case region name such as centralindia)")
    out.append(
        _check(
            "speech.credentials",
            SPEECH,
            "Speech resource (key and region)",
            Status.BLOCKED if problems else Status.PASS,
            "; ".join(problems) if problems else "key and region are configured.",
            "Create an Azure AI Speech resource (docs/DEPLOYMENT.md) and set the key and region." if problems else "",
        )
    )
    registry = load_registry()
    stt_locales = sorted({p.spec.stt_locale for p in registry.packs() if p.spec.status == "supported"})
    bad_voices = [
        locale
        for locale, voice in DEFAULT_VOICES.items()
        if locale in stt_locales and not is_known_voice(voice, locale)
    ]
    out.append(
        _check(
            "speech.locales",
            SPEECH,
            "Languages Sparta will recognise and speak",
            Status.WARNING if bad_voices else Status.PASS,
            "recognition locales: "
            + ", ".join(stt_locales)
            + "; default voices: "
            + ", ".join(f"{loc} {voice}" for loc, voice in sorted(DEFAULT_VOICES.items())),
            "Fix the default voice of: " + ", ".join(bad_voices) if bad_voices else "",
        )
    )
    return out


# ---------------------------------------------------------------------------------------------------- openai
def openai_checks(settings: Settings) -> list[Check]:
    if settings.llm_provider != "azure_openai":
        return [
            _check(
                "openai.selection",
                OPENAI,
                "Language model",
                Status.WARNING,
                "SPARTA_LLM_PROVIDER=rules: the deterministic engine decides everything and no model is called. That is "
                "a complete, safe configuration; a model only adds advisory signals and optional summaries.",
                "Set SPARTA_LLM_PROVIDER=azure_openai only if you want model assistance.",
            )
        ]
    problems = []
    if not settings.azure_openai_endpoint or https_origin(settings.azure_openai_endpoint) is None:
        problems.append("SPARTA_AZURE_OPENAI_ENDPOINT is missing or not an https URL")
    if not settings.azure_openai_key:
        problems.append("SPARTA_AZURE_OPENAI_KEY is missing")
    if not settings.azure_openai_deployment:
        problems.append("SPARTA_AZURE_OPENAI_DEPLOYMENT is missing")
    if not _API_VERSION.fullmatch(settings.azure_openai_api_version):
        problems.append("SPARTA_AZURE_OPENAI_API_VERSION is malformed (expected YYYY-MM-DD)")
    return [
        _check(
            "openai.credentials",
            OPENAI,
            "Model deployment (endpoint, key, deployment name)",
            Status.BLOCKED if problems else Status.PASS,
            "; ".join(problems) if problems else "endpoint, key and deployment name are configured.",
            "Create an Azure OpenAI deployment and set the three values." if problems else "",
        )
    ]


# ---------------------------------------------------------------------------------------------------- limits
def _per_minute_cost(settings: Settings) -> float:
    stt = settings.estimated_stt_per_audio_hour_usd / 60.0
    tts = settings.estimated_tts_per_million_chars_usd * ASSUMED_ASSISTANT_CHARS_PER_MINUTE / 1_000_000
    llm = 0.0
    if settings.llm_provider == "azure_openai":
        llm = ASSUMED_LLM_TURNS_PER_MINUTE * (
            settings.estimated_llm_per_million_prompt_tokens_usd * ASSUMED_LLM_PROMPT_TOKENS_PER_TURN / 1_000_000
            + settings.estimated_llm_per_million_completion_tokens_usd
            * ASSUMED_LLM_COMPLETION_TOKENS_PER_TURN
            / 1_000_000
        )
    return settings.estimated_telephony_per_minute_usd + stt + tts + llm


def limit_checks(settings: Settings) -> list[Check]:
    out: list[Check] = []
    minutes = settings.max_call_duration_s / 60.0
    duration_status = Status.WARNING if settings.max_call_duration_s > 1800 else Status.PASS
    out.append(
        _check(
            "limits.call_duration",
            LIMITS,
            "Maximum call duration",
            duration_status,
            f"{settings.max_call_duration_s} s per call (the owner's own limit can only be lower); abandoned calls are "
            f"closed after {settings.abandoned_call_timeout_s} s without activity.",
            "Keep calls short: a screening call needs a minute or two." if duration_status is Status.WARNING else "",
        )
    )
    minutes_cap = settings.daily_call_minutes_cap
    per_number = settings.per_number_daily_call_cap
    out.append(
        _check(
            "limits.call_caps",
            LIMITS,
            "Call volume caps",
            Status.PASS,
            f"at most {settings.max_active_calls} calls at once, {settings.daily_call_cap} calls and "
            + (f"{minutes_cap:g} call-minutes" if minutes_cap > 0 else "no minute limit")
            + " per owner per UTC day"
            + (f", and {per_number} real calls per caller number per day." if per_number > 0 else "."),
        )
    )
    per_minute = _per_minute_cost(settings)
    if per_minute <= 0:
        out.append(
            _check(
                "limits.cost_estimate",
                LIMITS,
                "Worst-case daily cost estimate",
                Status.WARNING,
                "no unit prices configured (SPARTA_ESTIMATED_* are 0), so no estimate can be shown.",
                "Copy your actual per-minute, per-hour and per-million prices into SPARTA_ESTIMATED_* to see a "
                "worst-case daily figure here.",
            )
        )
    else:
        by_calls = minutes * settings.daily_call_cap
        worst_minutes = min(by_calls, minutes_cap) if minutes_cap > 0 else by_calls
        worst = per_minute * worst_minutes
        out.append(
            _check(
                "limits.cost_estimate",
                LIMITS,
                "Worst-case daily cost estimate",
                Status.PASS,
                f"about {per_minute:.4f} USD per call-minute x {worst_minutes:.1f} min (the lower of "
                f"{minutes:.1f} min x {settings.daily_call_cap} calls and the daily minute cap) = {worst:.2f} USD per "
                f"day if every cap were reached. Assumes {ASSUMED_ASSISTANT_CHARS_PER_MINUTE} "
                f"spoken characters and {ASSUMED_LLM_TURNS_PER_MINUTE} model turns per minute (a diagnostic estimate "
                "from your own unit prices, not a bill).",
            )
        )
    return out


# ---------------------------------------------------------------------------------------------- number helpers
def number_check(settings: Settings, group: str = ACS, where: str = "the ACS resource") -> Check:
    number = settings.forwarding_number
    if not number:
        return _check(
            "telephony.inbound_number",
            group,
            "Inbound telephone number",
            Status.UNVERIFIED,
            "SPARTA_FORWARDING_NUMBER is not set: Sparta does not know which number callers dial.",
            "Set it to the provider's inbound number in E.164 form once one exists.",
        )
    if not _E164.fullmatch(number):
        return _check(
            "telephony.inbound_number",
            group,
            "Inbound telephone number",
            Status.BLOCKED,
            "SPARTA_FORWARDING_NUMBER is not an E.164 number (+, country code, digits).",
            "Use the form +<country code><number>.",
        )
    return _check(
        "telephony.inbound_number",
        group,
        "Inbound telephone number",
        Status.UNVERIFIED,
        f"configured ({mask_number(number)}); format is valid but ownership by the provider account is not proven.",
        f"Run with --online to look the number up on {where}.",
    )


def acs_connection_string_check(settings: Settings) -> Check:
    secret = settings.acs_connection_string
    if secret is None:
        return _check(
            "acs.connection_string",
            ACS,
            "ACS connection string",
            Status.BLOCKED,
            "SPARTA_ACS_CONNECTION_STRING is missing.",
            "Copy it from the ACS resource (Settings > Keys) into Key Vault, never into the repository.",
        )
    parts = dict(
        item.split("=", maxsplit=1) for item in secret.get_secret_value().strip().rstrip(";").split(";") if "=" in item
    )
    endpoint = parts.get("endpoint", "")
    key = parts.get("accesskey", "")
    host = urlsplit(endpoint).hostname or ""
    problems = []
    if not endpoint.startswith("https://") or not _ACS_HOST.fullmatch(host):
        problems.append("endpoint is not https://<resource>.communication.azure.com/")
    try:
        if not key or len(base64.b64decode(key, validate=True)) < 16:
            problems.append("accesskey is missing or too short")
    except (binascii.Error, ValueError):
        problems.append("accesskey is not base64")
    if problems:
        return _check(
            "acs.connection_string",
            ACS,
            "ACS connection string",
            Status.BLOCKED,
            "malformed: " + "; ".join(problems) + ".",
            "Expected endpoint=https://<resource>.communication.azure.com/;accesskey=<key>",
        )
    return _check(
        "acs.connection_string",
        ACS,
        "ACS connection string",
        Status.PASS,
        "configured and well-formed (the key itself is not checked until --online).",
    )


def acs_resource_id_check(settings: Settings) -> Check:
    value = settings.acs_resource_id
    if not value:
        return _check(
            "acs.resource_id",
            ACS,
            "ACS resource id (callback token audience)",
            Status.BLOCKED,
            "SPARTA_ACS_RESOURCE_ID is missing: callbacks from ACS cannot be authenticated without it.",
            "Use the ACS resource's id as shown in the portal (docs/TELEPHONY.md, 'Callback authentication').",
        )
    if _GUID.fullmatch(value.strip()):
        return _check(
            "acs.resource_id",
            ACS,
            "ACS resource id (callback token audience)",
            Status.UNVERIFIED,
            "configured as a GUID; whether ACS puts this exact form in the audience of its callback tokens has not "
            "been proven by a live callback.",
            "Place one test call and watch for 'webhook rejected' log lines with reason 'audience'.",
        )
    return _check(
        "acs.resource_id",
        ACS,
        "ACS resource id (callback token audience)",
        Status.WARNING,
        "configured but is not a GUID; the audience of ACS callback tokens is the resource's immutable id (a GUID).",
        "Check the value against the ACS resource's Overview page.",
    )


def callback_url_check(settings: Settings, override: str | None = None) -> Check:
    return _public_url_check(
        override or settings.acs_callback_base_url,
        "acs.callback_url",
        ACS,
        "SPARTA_ACS_CALLBACK_BASE_URL",
        "ACS",
    )


def twilio_callback_url_check(settings: Settings, override: str | None = None) -> Check:
    return _public_url_check(
        override or settings.twilio_callback_base_url,
        "twilio.callback_url",
        TWILIO,
        "SPARTA_TWILIO_CALLBACK_BASE_URL",
        "Twilio",
    )


def _public_url_check(raw: str | None, id_: str, group: str, name: str, provider: str) -> Check:
    if not raw:
        return _check(
            id_,
            group,
            "Public callback URL",
            Status.BLOCKED,
            f"{name} is missing.",
            "Set it to the API's public https origin (a dev tunnel is fine for a first test).",
        )
    origin = https_origin(raw)
    if origin is None:
        return _check(
            id_,
            group,
            "Public callback URL",
            Status.BLOCKED,
            "not a valid https origin (https only, no credentials, query or fragment).",
            "Use https://<public host name>.",
        )
    host = urlsplit(origin).hostname
    if not is_public_host(host):
        return _check(
            id_,
            group,
            "Public callback URL",
            Status.BLOCKED,
            f"the host is not publicly resolvable (localhost, a private address or a single-label name): {provider} "
            "cannot reach it.",
            "Expose the API through a public https host name.",
        )
    return _check(id_, group, "Public callback URL", Status.PASS, "an https URL on a public host name.")


def twilio_credentials_check(settings: Settings) -> list[Check]:
    out: list[Check] = []
    sid, token = settings.twilio_account_sid, settings.twilio_auth_token
    if not sid:
        out.append(
            _check(
                "twilio.account_sid",
                TWILIO,
                "Twilio account SID",
                Status.BLOCKED,
                "SPARTA_TWILIO_ACCOUNT_SID is missing.",
                "Copy it from the Twilio Console (Account Info); it starts with AC. Use the account SID, not an API key.",
            )
        )
    elif not _TWILIO_SID.fullmatch(sid):
        out.append(
            _check(
                "twilio.account_sid",
                TWILIO,
                "Twilio account SID",
                Status.BLOCKED,
                "malformed: expected AC followed by 32 lower-case hexadecimal digits.",
                "Use the account SID, not an API key (SK...) or a call SID (CA...).",
            )
        )
    else:
        out.append(
            _check("twilio.account_sid", TWILIO, "Twilio account SID", Status.PASS, "configured and well-formed.")
        )
    if token is None:
        out.append(
            _check(
                "twilio.auth_token",
                TWILIO,
                "Twilio auth token",
                Status.BLOCKED,
                "SPARTA_TWILIO_AUTH_TOKEN is missing.",
                "Store the account's auth token in Key Vault; it signs every webhook, so it is the only key Twilio "
                "requests can be verified with. An API key secret cannot be used.",
            )
        )
    elif not _TWILIO_TOKEN.fullmatch(token.get_secret_value().strip()):
        out.append(
            _check(
                "twilio.auth_token",
                TWILIO,
                "Twilio auth token",
                Status.WARNING,
                "configured, but it does not look like a 32-character hexadecimal auth token.",
                "Check that it is the account's Auth Token (not an API key secret).",
            )
        )
    else:
        out.append(
            _check(
                "twilio.auth_token",
                TWILIO,
                "Twilio auth token",
                Status.PASS,
                "configured (the value itself is not checked until --online).",
            )
        )
    return out


def twilio_options_check(settings: Settings) -> list[Check]:
    out: list[Check] = []
    caller_id = settings.twilio_caller_id
    if caller_id and not _E164.fullmatch(caller_id):
        out.append(
            _check(
                "twilio.caller_id",
                TWILIO,
                "Caller id presented on a takeover",
                Status.BLOCKED,
                "SPARTA_TWILIO_CALLER_ID is not an E.164 number.",
                "Use a number you own on Twilio or have verified there.",
            )
        )
    else:
        out.append(
            _check(
                "twilio.caller_id",
                TWILIO,
                "Caller id presented on a takeover",
                Status.PASS,
                "the Twilio number that was dialled is used." if not caller_id else "an explicit number is set.",
            )
        )
    if not settings.twilio_verify_media_signature:
        out.append(
            _check(
                "twilio.media_signature",
                TWILIO,
                "Media WebSocket signature",
                Status.WARNING,
                "SPARTA_TWILIO_VERIFY_MEDIA_SIGNATURE is off: only the per-call token authenticates the media socket.",
                "Turn it back on unless a live call proved that Twilio's upgrade signature does not verify.",
            )
        )
    return out


def event_grid_check(settings: Settings) -> Check:
    missing = [
        name
        for name, value in (
            ("SPARTA_ENTRA_TENANT_ID", settings.entra_tenant_id),
            ("SPARTA_EVENT_GRID_AUDIENCE", settings.event_grid_audience),
        )
        if not value
    ]
    if missing:
        return _check(
            "acs.event_grid_auth",
            ACS,
            "Event Grid delivery authentication",
            Status.BLOCKED,
            "missing: " + ", ".join(missing) + ". Without them Sparta rejects every Event Grid delivery (including "
            "the incoming-call event).",
            "Create the Entra application for the secure webhook and set the tenant id and audience (docs/TELEPHONY.md).",
        )
    app_ids = [item.strip() for item in (settings.event_grid_allowed_app_ids or "").split(",") if item.strip()]
    if not all(_GUID.fullmatch(app_id) for app_id in app_ids):
        return _check(
            "acs.event_grid_auth",
            ACS,
            "Event Grid delivery authentication",
            Status.BLOCKED,
            "SPARTA_EVENT_GRID_ALLOWED_APP_IDS must list application (client) id GUIDs, comma separated.",
            "Use the Application ID of the Microsoft.EventGrid service principal in your tenant.",
        )
    if not app_ids:
        return _check(
            "acs.event_grid_auth",
            ACS,
            "Event Grid delivery authentication",
            Status.WARNING,
            "tenant and audience are configured, but no calling application is pinned. The "
            "AzureEventGridSecureWebhookSubscriber role is also granted to the subscription-writer app, so the role "
            "alone does not show that Event Grid is the caller.",
            "Set SPARTA_EVENT_GRID_ALLOWED_APP_IDS to the Microsoft.EventGrid application id of your cloud "
            "(Entra admin centre > Enterprise applications, or: az ad sp list --display-name Microsoft.EventGrid "
            "--query [].appId -o tsv).",
        )
    return _check(
        "acs.event_grid_auth",
        ACS,
        "Event Grid delivery authentication",
        Status.PASS,
        "tenant, audience and the calling application are configured.",
    )


def acs_sdk_check() -> Check:
    """The Call Automation SDK is an optional extra: a default install has no way to answer an ACS call."""
    try:
        version = importlib.metadata.version("azure-communication-callautomation")
    except importlib.metadata.PackageNotFoundError:
        return _check(
            "acs.sdk",
            ACS,
            "Call Automation SDK installed",
            Status.BLOCKED,
            "azure-communication-callautomation is not installed.",
            "Install the azure extra: pip install 'sparta-api[azure]' (the container image already has it).",
        )
    try:
        from azure.communication.callautomation import AudioFormat

        has_format = hasattr(AudioFormat, "PCM16_K_MONO")
    except ImportError:
        has_format = False
    if not has_format:
        return _check(
            "acs.sdk",
            ACS,
            "Call Automation SDK installed",
            Status.BLOCKED,
            f"azure-communication-callautomation {version} has no 16 kHz PCM media streaming format.",
            "Install a release that supports bidirectional media streaming (1.4.0 or newer).",
        )
    return _check(
        "acs.sdk",
        ACS,
        "Call Automation SDK installed",
        Status.PASS,
        f"azure-communication-callautomation {version} with 16 kHz PCM media streaming.",
    )


def speech_sdk_check(settings: Settings) -> Check:
    """Streaming recognition (partial transcripts) uses the Speech SDK; without it recognition is per utterance."""
    try:
        version = importlib.metadata.version("azure-cognitiveservices-speech")
    except importlib.metadata.PackageNotFoundError:
        return _check(
            "speech.sdk",
            SPEECH,
            "Speech SDK installed (streaming recognition)",
            Status.WARNING,
            "azure-cognitiveservices-speech is not installed: recognition falls back to one request per utterance "
            "(no partial transcripts, extra latency).",
            "Install the azure extra: pip install 'sparta-api[azure]'.",
        )
    return _check(
        "speech.sdk",
        SPEECH,
        "Speech SDK installed (streaming recognition)",
        Status.PASS,
        f"azure-cognitiveservices-speech {version}.",
    )


def media_format_check(telephony: str = "azure") -> Check:
    """What the media socket code expects from the provider. It is a statement about this code, not about a live call."""
    if telephony == "twilio":
        from sparta.telephony.twilio import FRAME_BYTES, SAMPLE_RATE

        return _check(
            "media.format",
            TWILIO,
            "Expected media format",
            Status.PASS,
            f"mono mu-law at {SAMPLE_RATE // 1000} kHz both ways ({FRAME_BYTES} bytes per 20 ms frame, base64 in JSON "
            "messages), converted to PCM16 for recognition. Whether a live Twilio call sends exactly this is listed "
            "under 'Not provable from here'.",
        )
    from sparta.telephony.azure_acs import DEFAULT_SAMPLE_RATE, FRAME_MS, OUTPUT_FORMAT_BY_RATE

    frame = DEFAULT_SAMPLE_RATE * FRAME_MS // 1000 * 2
    rates = ", ".join(f"{rate // 1000} kHz" for rate in sorted(OUTPUT_FORMAT_BY_RATE))
    return _check(
        "media.format",
        ACS,
        "Expected media format",
        Status.PASS,
        f"mono PCM16 at {DEFAULT_SAMPLE_RATE // 1000} kHz requested from ACS; {FRAME_MS} ms frames ({frame} bytes); "
        f"accepted sample rates: {rates}. Whether a live ACS call sends exactly this is listed under 'Not provable "
        "from here'.",
    )
