"""``sparta doctor``: it must tell a configuration that cannot take a real call from one that can, say honestly what it
cannot prove, and never print a secret value."""

import base64
import json
import socket
import sys
import types

import httpx
import pytest
from cryptography.fernet import Fernet

from sparta import cli
from sparta.config import ConfigurationError, Settings
from sparta.db.models import Base
from sparta.db.session import Database
from sparta.doctor import Status, run_doctor
from sparta.doctor import checks as c
from sparta.doctor.billable import run_billable
from sparta.doctor.model import Check, DoctorReport
from sparta.doctor.online import Unreachable, fetch
from sparta.doctor.runner import ReportingSettings, normalise_providers

ACS_KEY = base64.b64encode(b"acs-secret-sentinel-0123456789ab").decode()
SPEECH_KEY = "speech-key-SENTINEL-9f3a"
OPENAI_KEY = "openai-key-SENTINEL-7c1d"
PEPPER = "pepper-SENTINEL-55aa"
WEBHOOK_SECRET = "webhook-secret-SENTINEL-1b2c"
DATA_KEY = Fernet.generate_key().decode()
NUMBER = "+15551230001"
SECRETS = (ACS_KEY, SPEECH_KEY, OPENAI_KEY, PEPPER, WEBHOOK_SECRET, DATA_KEY, "15551230001")
HOST = "sparta.example.com"


def azure_settings(*, reporting: bool = False, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "telephony_provider": "azure",
        "stt_provider": "azure",
        "tts_provider": "azure",
        "acs_connection_string": f"endpoint=https://sparta-test.communication.azure.com/;accesskey={ACS_KEY}",
        "acs_callback_base_url": f"https://{HOST}",
        "acs_resource_id": "11111111-2222-3333-4444-555555555555",
        "entra_tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "event_grid_audience": "api://sparta-event-grid",
        "azure_speech_key": SPEECH_KEY,
        "azure_speech_region": "centralindia",
        "forwarding_number": NUMBER,
        "data_keys": DATA_KEY,
        "pepper": PEPPER,
        "webhook_secret": WEBHOOK_SECRET,
        "trusted_hosts": [HOST],
        "cors_origins": ["https://app.example.com"],
        "redis_url": "redis://localhost:6379/0",
        "database_url": "postgresql+asyncpg://u:p@db.example.com:5432/sparta",
        "auth_mode": "oidc",
        "oidc_issuer": "https://login.example.com/",
        "oidc_audience": "api://sparta",
    }
    values.update(overrides)
    cls = ReportingSettings if reporting else Settings
    return cls(_env_file=None, **values)  # type: ignore[arg-type]


def by_id(report: DoctorReport) -> dict[str, Check]:
    return {check.id: check for check in report.checks}


@pytest.fixture(autouse=True)
def sdk_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The optional SDKs may or may not be installed where the tests run: pretend they are."""
    monkeypatch.setattr(c, "acs_sdk_check", lambda: Check("acs.sdk", c.ACS, "sdk", Status.PASS))
    monkeypatch.setattr(c, "speech_sdk_check", lambda s: Check("speech.sdk", c.SPEECH, "sdk", Status.PASS))


# ---------------------------------------------------------------------------------------------------- offline
async def test_the_default_configuration_is_blocked_and_says_why():
    report = await run_doctor(Settings(_env_file=None))
    checks = by_id(report)
    assert report.blocked and report.exit_code() == 1
    assert checks["provider.selection"].status is Status.BLOCKED
    assert checks["core.environment"].status is Status.WARNING
    assert "NOT READY" in report.render_text()


async def test_a_complete_azure_configuration_has_no_blocker_offline():
    report = await run_doctor(azure_settings())
    assert not report.blocked, [(x.id, x.detail) for x in report.checks if x.status is Status.BLOCKED]
    assert report.exit_code() == 0
    checks = by_id(report)
    assert checks["acs.callback_url"].status is Status.PASS
    assert checks["acs.connection_string"].status is Status.PASS
    # A green configuration is never described as a working phone line.
    assert checks["live.pstn_inbound"].status is Status.UNVERIFIED
    assert checks["legal.review"].status is Status.UNVERIFIED
    assert "cannot be proven" in report.verdict()


async def test_no_secret_value_is_ever_printed_in_text_or_json():
    report = await run_doctor(
        azure_settings(
            llm_provider="azure_openai",
            azure_openai_key=OPENAI_KEY,
            azure_openai_endpoint="https://o.openai.azure.com",
            azure_openai_deployment="gpt",
        )
    )
    for rendered in (report.render_text(), report.render_json(), report.render_text(colour=True)):
        for secret in SECRETS:
            assert secret not in rendered
    assert "+1555" not in report.render_text()  # the inbound number is masked


@pytest.mark.parametrize(
    "connection_string",
    [
        "endpoint=http://x.communication.azure.com/;accesskey=" + ACS_KEY,
        "endpoint=https://evil.example.com/;accesskey=" + ACS_KEY,
        "endpoint=https://x.communication.azure.com/;accesskey=not base64!!",
        "endpoint=https://x.communication.azure.com/",
        "garbage",
    ],
)
async def test_a_malformed_acs_connection_string_is_blocked_without_echoing_it(connection_string):
    report = await run_doctor(azure_settings(acs_connection_string=connection_string))
    check = by_id(report)["acs.connection_string"]
    assert check.status is Status.BLOCKED and "malformed" in check.detail
    assert "evil.example.com" not in check.detail and "not base64!!" not in report.render_text()


@pytest.mark.parametrize(
    ("url", "status"),
    [
        (f"https://{HOST}", Status.PASS),
        (f"https://{HOST}:8443/sparta", Status.PASS),
        (f"http://{HOST}", Status.BLOCKED),
        ("https://localhost:8000", Status.BLOCKED),
        ("https://127.0.0.1", Status.BLOCKED),
        ("https://10.0.0.5", Status.BLOCKED),
        ("https://intranet", Status.BLOCKED),
        ("https://user:pw@sparta.example.com", Status.BLOCKED),
    ],
)
async def test_the_callback_url_must_be_a_public_https_origin(url, status):
    report = await run_doctor(azure_settings(acs_callback_base_url=url, trusted_hosts=["*"]))
    assert by_id(report)["acs.callback_url"].status is status


async def test_the_development_identity_on_a_public_url_is_blocked_unless_only_provider_routes_are_served():
    open_dev = by_id(await run_doctor(azure_settings(auth_mode="dev")))["core.auth"]
    assert open_dev.status is Status.BLOCKED and "anyone who can reach" in open_dev.detail
    guarded = by_id(await run_doctor(azure_settings(auth_mode="dev", provider_only_hosts=[HOST])))["core.auth"]
    assert guarded.status is Status.WARNING
    local = by_id(await run_doctor(azure_settings(auth_mode="dev", acs_callback_base_url="https://localhost")))
    assert local["core.auth"].status is Status.WARNING


async def test_oidc_is_unverified_even_when_complete_and_blocked_when_incomplete():
    assert by_id(await run_doctor(azure_settings()))["core.auth"].status is Status.UNVERIFIED
    broken = azure_settings(oidc_audience=None)
    assert by_id(await run_doctor(broken))["core.auth"].status is Status.BLOCKED


async def test_a_production_configuration_is_reported_not_raised():
    with pytest.raises(ConfigurationError):
        Settings(_env_file=None, env="production")
    settings = ReportingSettings(_env_file=None, env="production")
    report = await run_doctor(settings)
    startup = [check for check in report.checks if check.id.startswith("core.startup.")]
    assert startup and all(check.status is Status.BLOCKED for check in startup)
    assert any("SPARTA_DATA_KEYS" in check.detail for check in startup)


async def test_the_callback_host_must_be_trusted():
    report = await run_doctor(azure_settings(trusted_hosts=["other.example.com"]))
    assert by_id(report)["http.trusted_hosts"].status is Status.BLOCKED
    wildcard = await run_doctor(azure_settings(reporting=True, trusted_hosts=["*"], env="production"))
    assert by_id(wildcard)["http.trusted_hosts"].status is Status.BLOCKED


async def test_provider_only_hosts_without_explicit_trusted_hosts_are_blocked_because_the_server_would_not_start():
    unbacked = await run_doctor(azure_settings(trusted_hosts=["*"], provider_only_hosts=[HOST]))
    check = by_id(unbacked)["http.trusted_hosts"]
    assert check.status is Status.BLOCKED and "refuses to start" in check.detail
    backed = await run_doctor(azure_settings(trusted_hosts=[HOST, "localhost"], provider_only_hosts=[HOST]))
    assert by_id(backed)["http.trusted_hosts"].status is Status.PASS
    # a wildcard on its own stays a warning outside production, as before
    assert by_id(await run_doctor(azure_settings(trusted_hosts=["*"])))["http.trusted_hosts"].status is Status.WARNING


async def test_the_inbound_number_is_validated_and_never_proven_offline():
    ok = by_id(await run_doctor(azure_settings()))["telephony.inbound_number"]
    assert ok.status is Status.UNVERIFIED and NUMBER not in ok.detail
    bad = by_id(await run_doctor(azure_settings(forwarding_number="0044 7700 900123")))["telephony.inbound_number"]
    assert bad.status is Status.BLOCKED
    missing = by_id(await run_doctor(azure_settings(forwarding_number=None)))["telephony.inbound_number"]
    assert missing.status is Status.UNVERIFIED


async def test_event_grid_deliveries_should_be_pinned_to_the_calling_application():
    unpinned = by_id(await run_doctor(azure_settings()))["acs.event_grid_auth"]
    assert unpinned.status is Status.WARNING and "subscription-writer" in unpinned.detail
    pinned = azure_settings(event_grid_allowed_app_ids="4962773b-9cdb-44cf-a8bf-237846a00ab7")
    assert by_id(await run_doctor(pinned))["acs.event_grid_auth"].status is Status.PASS
    malformed = azure_settings(reporting=True, event_grid_allowed_app_ids="Microsoft.EventGrid")
    assert by_id(await run_doctor(malformed))["acs.event_grid_auth"].status is Status.BLOCKED


async def test_the_resource_id_must_look_like_what_acs_puts_in_its_tokens():
    guid = by_id(await run_doctor(azure_settings()))["acs.resource_id"]
    assert guid.status is Status.UNVERIFIED
    arm = azure_settings(
        acs_resource_id="/subscriptions/s/resourceGroups/rg/providers/Microsoft.Communication/communicationServices/x"
    )
    assert by_id(await run_doctor(arm))["acs.resource_id"].status is Status.WARNING
    assert by_id(await run_doctor(azure_settings(acs_resource_id=None)))["acs.resource_id"].status is Status.BLOCKED


async def test_a_real_provider_selection_must_cover_every_stage_of_a_call():
    deaf = by_id(await run_doctor(azure_settings(stt_provider="simulator")))["provider.selection"]
    assert deaf.status is Status.BLOCKED and "speech recognition" in deaf.detail
    assert by_id(await run_doctor(azure_settings()))["provider.selection"].status is Status.PASS


async def test_the_cost_estimate_uses_the_owners_own_prices_and_states_its_assumptions():
    settings = azure_settings(
        estimated_telephony_per_minute_usd=0.01,
        estimated_stt_per_audio_hour_usd=1.0,
        estimated_tts_per_million_chars_usd=15.0,
        daily_call_cap=10,
        max_call_duration_s=300,
    )
    detail = by_id(await run_doctor(settings))["limits.cost_estimate"].detail
    assert "1.67 USD per day" in detail and "450 spoken characters" in detail and "not a bill" in detail
    capped = azure_settings(
        estimated_telephony_per_minute_usd=0.01,
        estimated_stt_per_audio_hour_usd=1.0,
        estimated_tts_per_million_chars_usd=15.0,
        daily_call_cap=10,
        max_call_duration_s=300,
        daily_call_minutes_cap=10,
    )
    report = await run_doctor(capped)
    assert "0.33 USD per day" in by_id(report)["limits.cost_estimate"].detail  # the minute cap binds: 10 min, not 50
    assert "10 call-minutes" in by_id(report)["limits.call_caps"].detail
    unpriced = by_id(await run_doctor(azure_settings()))["limits.cost_estimate"]
    assert unpriced.status is Status.WARNING
    long_calls = by_id(await run_doctor(azure_settings(max_call_duration_s=7200)))["limits.call_duration"]
    assert long_calls.status is Status.WARNING


def test_the_sdk_checks_report_a_missing_or_old_sdk(monkeypatch):
    monkeypatch.undo()  # use the real checks
    import importlib.metadata

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError(name)),
    )
    assert c.acs_sdk_check().status is Status.BLOCKED
    assert c.speech_sdk_check(Settings(_env_file=None)).status is Status.WARNING
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.6.1")
    fake = types.ModuleType("azure.communication.callautomation")
    fake.AudioFormat = types.SimpleNamespace(PCM16_K_MONO="PCM16_K_MONO")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.communication.callautomation", fake)
    assert c.acs_sdk_check().status is Status.PASS
    fake.AudioFormat = types.SimpleNamespace()  # type: ignore[attr-defined]
    assert c.acs_sdk_check().status is Status.BLOCKED


def test_provider_names_are_validated():
    assert normalise_providers(["all"]) == ("azure", "twilio", "simulator")
    assert normalise_providers(["azure", "azure"]) == ("azure",)
    with pytest.raises(ValueError, match="unknown provider"):
        normalise_providers(["plivo"])


async def test_the_simulator_scope_says_it_did_not_check_a_phone_line():
    report = await run_doctor(Settings(_env_file=None), providers=["simulator"])
    assert by_id(report)["doctor.scope"].status is Status.WARNING
    assert "live.pstn_inbound" not in by_id(report)


# ----------------------------------------------------------------------------------------------------- report
def test_report_rendering_counts_sorts_and_redacts():
    report = DoctorReport(providers=("azure",))
    report.add(Check("a", "G", "fine", Status.PASS))
    report.add(Check("b", "G", "bad", Status.BLOCKED, "token=abc123secret", "fix it"))
    report.add(Check("c", "G", "later", Status.UNVERIFIED, "needs a call", "place one"))
    text = report.render_text()
    assert text.index("bad") < text.index("later") < text.index("fine")
    assert "abc123secret" not in text and "token=[redacted]" in text
    assert report.counts() == {Status.PASS: 1, Status.WARNING: 0, Status.BLOCKED: 1, Status.UNVERIFIED: 1}
    assert json.loads(report.render_json())["summary"]["BLOCKED"] == 1
    assert (
        report.exit_code() == 1 and DoctorReport().exit_code() == 0 and DoctorReport().verdict() == "NO BLOCKERS FOUND"
    )


# ------------------------------------------------------------------------------------------------------ online
VOICES = [{"ShortName": "en-IN-NeerjaNeural"}, {"ShortName": "hi-IN-SwaraNeural"}, {"ShortName": "kn-IN-SapnaNeural"}]


def good_handler(
    overrides: dict[str, httpx.Response | Exception] | None = None, seen: list[httpx.Request] | None = None
):
    table: dict[str, httpx.Response | Exception] = {
        f"GET https://{HOST}/healthz": httpx.Response(200, json={"status": "ok"}),
        f"GET https://{HOST}/readyz": httpx.Response(200, json={"status": "ready", "checks": {"database": "ok"}}),
        f"POST https://{HOST}/api/v1/webhooks/acs/events": httpx.Response(401),
        f"GET https://{HOST}/api/v1/media/acs/doctorprobe": httpx.Response(403),
        "POST https://centralindia.api.cognitive.microsoft.com/sts/v1.0/issueToken": httpx.Response(200, text="jwt"),
        "GET https://centralindia.tts.speech.microsoft.com/cognitiveservices/voices/list": httpx.Response(
            200, json=VOICES
        ),
        "GET https://login.example.com/.well-known/jwks.json": httpx.Response(
            200, json={"keys": [{"kty": "RSA", "kid": "k1", "n": "x", "e": "AQAB"}]}
        ),
    }
    table.update(overrides or {})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        outcome = table.get(f"{request.method} {request.url.copy_with(query=None)}")
        if outcome is None:
            return httpx.Response(404)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return handler


@pytest.fixture
async def sqlite_url(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'doctor.db').as_posix()}"
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await database.dispose()
    return url


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_every_online_check_can_pass_and_the_unprovable_ones_stay_unverified(sqlite_url):
    seen: list[httpx.Request] = []
    settings = azure_settings(database_url=sqlite_url, redis_url=None)
    async with client_for(good_handler(seen=seen)) as http:
        report = await run_doctor(settings, online=True, http=http)
    checks = by_id(report)
    for ident in (
        "callback.health",
        "callback.ready",
        "callback.webhook_auth",
        "callback.media_auth",
        "speech.token",
        "speech.voices",
        "db.connect",
        "db.schema",
    ):
        assert checks[ident].status is Status.PASS, (ident, checks[ident].detail)
    assert checks["callback.external"].status is Status.UNVERIFIED
    assert not report.blocked
    key_requests = [r for r in seen if "Ocp-Apim-Subscription-Key" in r.headers]
    assert key_requests and all(r.headers["Ocp-Apim-Subscription-Key"] == SPEECH_KEY for r in key_requests)
    assert all(r.url.scheme == "https" for r in seen)
    for secret in SECRETS:
        assert secret not in report.render_text() + report.render_json()


async def test_an_unauthenticated_webhook_or_media_socket_is_blocked(sqlite_url):
    handler = good_handler(
        {
            f"POST https://{HOST}/api/v1/webhooks/acs/events": httpx.Response(200),
            f"GET https://{HOST}/api/v1/media/acs/doctorprobe": httpx.Response(101),
        }
    )
    async with client_for(handler) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    checks = by_id(report)
    assert checks["callback.webhook_auth"].status is Status.BLOCKED
    assert "UNAUTHENTICATED" in checks["callback.webhook_auth"].detail
    assert checks["callback.media_auth"].status is Status.BLOCKED


async def test_a_deployment_without_the_acs_routes_or_websockets_is_called_out(sqlite_url):
    handler = good_handler(
        {
            f"POST https://{HOST}/api/v1/webhooks/acs/events": httpx.Response(404),
            f"GET https://{HOST}/api/v1/media/acs/doctorprobe": httpx.Response(426),
        }
    )
    async with client_for(handler) as http:
        checks = by_id(
            await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
        )
    assert (
        checks["callback.webhook_auth"].status is Status.BLOCKED and "azure" in checks["callback.webhook_auth"].detail
    )
    assert checks["callback.media_auth"].status is Status.BLOCKED and "WebSockets" in checks["callback.media_auth"].fix


async def test_an_unreachable_callback_host_is_reported_without_the_url_or_exception_text(sqlite_url):
    error = httpx.ConnectError("[Errno -2] Name or service not known https://sparta.example.com/secret-path")
    error.__cause__ = socket.gaierror("dns")
    async with client_for(good_handler({f"GET https://{HOST}/healthz": error})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    check = by_id(report)["callback.health"]
    assert check.status is Status.BLOCKED and "host name was not found" in check.detail
    assert "secret-path" not in report.render_text() and "callback.ready" not in by_id(report)


@pytest.mark.parametrize(
    ("status", "needle"),
    [(400, "SPARTA_TRUSTED_HOSTS"), (502, "HTTP 502")],
)
async def test_other_health_failures_are_explained(sqlite_url, status, needle):
    async with client_for(good_handler({f"GET https://{HOST}/healthz": httpx.Response(status)})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    check = by_id(report)["callback.health"]
    assert check.status is Status.BLOCKED and needle in check.detail + check.fix


async def test_a_not_ready_deployment_is_blocked_with_the_reason(sqlite_url):
    ready = httpx.Response(503, json={"status": "unavailable", "checks": {"database": "migrations_pending"}})
    async with client_for(good_handler({f"GET https://{HOST}/readyz": ready})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    check = by_id(report)["callback.ready"]
    assert check.status is Status.BLOCKED and "migrations_pending" in check.detail


async def test_what_a_remote_readyz_says_is_shown_as_short_plain_text_and_cannot_drive_the_terminal(sqlite_url):
    checks = {"database\x1b[2J": "ok\x1b]0;owned\x07" + "x" * 500, "é" * 5: "\u202eevil"}
    checks.update({f"k{i}": "v" for i in range(40)})
    ready = httpx.Response(200, json={"checks": checks})
    async with client_for(good_handler({f"GET https://{HOST}/readyz": ready})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    detail = by_id(report)["callback.ready"].detail
    assert "\x1b" not in detail and "\x07" not in detail and "\u202e" not in detail
    assert len(detail) < 1100 and detail.count(": ") <= 12  # at most twelve entries, each of bounded length


def test_no_check_text_can_carry_control_characters_into_a_terminal():
    safe = Check("x", "g", "t\x1b[2J", Status.PASS, "a\x1b[31mred\x00\x07 b\nc\td", "fix\x9b").safe()
    assert "\x1b" not in safe.title + safe.detail + safe.fix
    assert (
        not any(ch in safe.detail + safe.fix for ch in "\x00\x07\x9b") and "\n" in safe.detail and "\t" in safe.detail
    )


async def test_a_rejected_speech_key_and_a_missing_default_voice_are_blocked(sqlite_url):
    token = "POST https://centralindia.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with client_for(good_handler({token: httpx.Response(401)})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    assert by_id(report)["speech.token"].status is Status.BLOCKED
    assert "speech.voices" not in by_id(report)
    voices = "GET https://centralindia.tts.speech.microsoft.com/cognitiveservices/voices/list"
    partial = httpx.Response(200, json=[{"ShortName": "en-IN-NeerjaNeural"}])
    async with client_for(good_handler({voices: partial})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    check = by_id(report)["speech.voices"]
    assert check.status is Status.BLOCKED and "hi-IN" in check.detail and "kn-IN" in check.detail


async def test_a_custom_domain_speech_endpoint_is_used(sqlite_url):
    seen: list[httpx.Request] = []
    base = "https://sparta-speech.cognitiveservices.azure.com"
    handler = good_handler(
        {
            f"POST {base}/sts/v1.0/issueToken": httpx.Response(200, text="jwt"),
            f"GET {base}/tts/cognitiveservices/voices/list": httpx.Response(200, json=VOICES),
        },
        seen,
    )
    settings = azure_settings(
        database_url=sqlite_url, redis_url=None, azure_speech_endpoint=base, azure_speech_region=None
    )
    async with client_for(handler) as http:
        report = await run_doctor(settings, online=True, http=http)
    assert by_id(report)["speech.token"].status is Status.PASS
    assert by_id(report)["speech.voices"].status is Status.PASS


async def test_the_model_endpoint_check_distinguishes_a_bad_key_from_an_unproven_deployment(sqlite_url):
    base = "https://o.openai.azure.com"
    kwargs = {
        "database_url": sqlite_url,
        "redis_url": None,
        "llm_provider": "azure_openai",
        "azure_openai_endpoint": base,
        "azure_openai_key": OPENAI_KEY,
        "azure_openai_deployment": "gpt",
    }
    models = f"GET {base}/openai/models"
    for status, expected in ((200, Status.PASS), (401, Status.BLOCKED), (500, Status.WARNING)):
        async with client_for(good_handler({models: httpx.Response(status)})) as http:
            report = await run_doctor(azure_settings(**kwargs), online=True, http=http)
        assert by_id(report)["openai.models"].status is expected


async def test_a_missing_database_schema_and_an_unreachable_redis_are_blocked(tmp_path):
    settings = azure_settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = azure_settings(database_url=settings.database_url, redis_url=f"redis://:hunter2@127.0.0.1:{port}/0")
    async with client_for(good_handler()) as http:
        report = await run_doctor(settings, online=True, http=http)
    checks = by_id(report)
    assert checks["db.schema"].status is Status.BLOCKED and "migrate" in checks["db.schema"].fix
    assert checks["redis.connect"].status is Status.BLOCKED
    assert "hunter2" not in report.render_text()


async def test_oidc_signing_keys_are_fetched_and_checked(sqlite_url):
    url = "https://login.example.com/.well-known/jwks.json"
    jwks = httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "k1", "n": "x", "e": "AQAB"}]})
    async with client_for(good_handler({f"GET {url}": jwks})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    assert by_id(report)["oidc.jwks"].status is Status.PASS
    async with client_for(good_handler({f"GET {url}": httpx.Response(200, json={"keys": []})})) as http:
        report = await run_doctor(azure_settings(database_url=sqlite_url, redis_url=None), online=True, http=http)
    assert by_id(report)["oidc.jwks"].status is Status.BLOCKED


async def test_fetch_never_follows_redirects_and_maps_failures_to_static_reasons():
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    async with client_for(redirect) as http:
        reply = await fetch(http, "GET", "https://x.example.com/a", headers={"api-key": "k"})
    assert reply.status == 302

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("took too long calling https://x.example.com/a")

    async with client_for(boom) as http:
        with pytest.raises(Unreachable) as caught:
            await fetch(http, "GET", "https://x.example.com/a")
    assert caught.value.reason == "the request timed out" and "x.example.com" not in caught.value.reason


# ---------------------------------------------------------------------------------------------------- billable
def synthesised(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"\x01\x02" * 16000)


RECOGNISED = {
    "durationMilliseconds": 1000,
    "combinedPhrases": [{"channel": 0, "text": "hello this is a test"}],
    "phrases": [
        {"locale": "en-IN", "confidence": 0.9, "offsetMilliseconds": 0, "durationMilliseconds": 1000, "text": "hello"}
    ],
}


async def test_the_billable_probes_exercise_the_production_adapters(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "centralindia.tts.speech.microsoft.com":
            return synthesised(request)
        if "transcriptions:transcribe" in request.url.path:
            return httpx.Response(200, json=RECOGNISED)
        if "/chat/completions" in request.url.path:
            body = json.dumps(
                {
                    "extra_signals": [],
                    "claimed_name": None,
                    "claimed_organization": None,
                    "purpose": "parcel",
                    "intent": None,
                    "notes": "",
                }
            )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": body}}
                    ],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 20, "total_tokens": 110},
                },
            )
        return httpx.Response(404)

    settings = azure_settings(
        llm_provider="azure_openai",
        azure_openai_endpoint="https://o.openai.azure.com",
        azure_openai_key=OPENAI_KEY,
        azure_openai_deployment="gpt",
    )
    async with client_for(handler) as http:
        checks = await run_billable(settings, http=http, timeout_s=5)
    by = {check.id: check for check in checks}
    assert [by[f"speech.roundtrip.{loc}"].status for loc in ("en-IN", "hi-IN", "kn-IN")] == [Status.PASS] * 3
    assert by["openai.probe"].status is Status.PASS and "90 prompt" in by["openai.probe"].detail
    assert "hello this is a test" not in "".join(check.detail for check in checks)


async def test_billable_failures_are_blocked_with_a_sanitised_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "centralindia.tts.speech.microsoft.com":
            return httpx.Response(401, text="Invalid key SECRET-BODY")
        return httpx.Response(400, text="Unsupported parameter: max_tokens SECRET-BODY")

    settings = azure_settings(
        llm_provider="azure_openai",
        azure_openai_endpoint="https://o.openai.azure.com",
        azure_openai_key=OPENAI_KEY,
        azure_openai_deployment="gpt",
    )
    async with client_for(handler) as http:
        checks = await run_billable(settings, http=http, timeout_s=5)
    assert all(check.status is Status.BLOCKED for check in checks)
    assert "SECRET-BODY" not in " ".join(check.detail + check.fix for check in checks)
    assert any("max_completion_tokens" in check.fix for check in checks)


async def test_the_billable_probes_only_run_when_explicitly_allowed(sqlite_url):
    calls: list[httpx.Request] = []
    handler = good_handler(seen=calls)
    settings = azure_settings(database_url=sqlite_url, redis_url=None)
    async with client_for(handler) as http:
        report = await run_doctor(settings, online=True, allow_billable=False, http=http)
    assert not any("tts.speech.microsoft.com/cognitiveservices/v1" in str(r.url) for r in calls)
    assert report.billable is False
    offline = await run_doctor(settings, online=False, allow_billable=True)
    assert offline.online is False and offline.billable is False  # --allow-billable means nothing without --online


# ------------------------------------------------------------------------------------------------------- Twilio
TWILIO_SID = "AC" + "0123456789abcdef" * 2
TWILIO_TOKEN = "fedcba9876543210fedcba9876543210"
VOICE_URL = f"https://{HOST}/api/v1/webhooks/twilio/voice"
TWILIO_ACCOUNT_URL = f"GET https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}.json"
TWILIO_NUMBERS_URL = f"GET https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/IncomingPhoneNumbers.json"
NUMBER_ROW = {"phone_number": NUMBER, "voice_url": VOICE_URL, "voice_method": "POST", "voice_application_sid": None}
ACTIVE = httpx.Response(200, json={"status": "active", "type": "Full"})


def twilio_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "telephony_provider": "twilio",
        "twilio_account_sid": TWILIO_SID,
        "twilio_auth_token": TWILIO_TOKEN,
        "twilio_callback_base_url": f"https://{HOST}",
    }
    values.update(overrides)
    return azure_settings(**values)


def twilio_handler(overrides: dict[str, httpx.Response | Exception] | None = None, seen=None):
    table: dict[str, httpx.Response | Exception] = {
        f"POST https://{HOST}/api/v1/webhooks/twilio/voice": httpx.Response(401),
        f"GET https://{HOST}/api/v1/media/twilio/doctorprobe": httpx.Response(403),
        TWILIO_ACCOUNT_URL: ACTIVE,
        TWILIO_NUMBERS_URL: httpx.Response(200, json={"incoming_phone_numbers": [NUMBER_ROW]}),
    }
    table.update(overrides or {})
    return good_handler(table, seen)


async def twilio_report(sqlite_url, overrides=None, seen=None, **settings):
    handler = twilio_handler(overrides, seen)
    async with client_for(handler) as http:
        return await run_doctor(
            twilio_settings(database_url=sqlite_url, redis_url=None, **settings),
            providers=("twilio",),
            online=True,
            http=http,
        )


async def test_a_complete_twilio_configuration_has_no_blocker_offline_and_says_what_is_unproven():
    report = await run_doctor(twilio_settings(), providers=("twilio",))
    checks = by_id(report)
    assert not report.blocked, [(x.id, x.detail) for x in report.checks if x.status is Status.BLOCKED]
    for ident in ("provider.selection", "twilio.account_sid", "twilio.auth_token", "twilio.callback_url"):
        assert checks[ident].status is Status.PASS, (ident, checks[ident].detail)
    assert checks["telephony.inbound_number"].status is Status.UNVERIFIED
    assert checks["live.twilio_media_stream"].status is Status.UNVERIFIED
    assert checks["live.pstn_inbound"].status is Status.UNVERIFIED and "mu-law" in checks["media.format"].detail
    assert not any(ident.startswith("acs.") for ident in checks) and "live.event_grid_subscription" not in checks
    assert TWILIO_TOKEN not in report.render_text() + report.render_json()


@pytest.mark.parametrize(
    ("overrides", "ident", "status"),
    [
        ({"twilio_account_sid": None}, "twilio.account_sid", Status.BLOCKED),
        ({"twilio_account_sid": "SK" + "0" * 32}, "twilio.account_sid", Status.BLOCKED),
        ({"twilio_account_sid": "CA" + "0" * 32}, "twilio.account_sid", Status.BLOCKED),
        ({"twilio_auth_token": None}, "twilio.auth_token", Status.BLOCKED),
        ({"twilio_auth_token": "not-a-twilio-token"}, "twilio.auth_token", Status.WARNING),
        ({"twilio_callback_base_url": None}, "twilio.callback_url", Status.BLOCKED),
        ({"twilio_callback_base_url": "http://sparta.example.com"}, "twilio.callback_url", Status.BLOCKED),
        ({"twilio_callback_base_url": "https://localhost:8000"}, "twilio.callback_url", Status.BLOCKED),
        ({"twilio_caller_id": "0044123"}, "twilio.caller_id", Status.BLOCKED),
        ({"twilio_verify_media_signature": False}, "twilio.media_signature", Status.WARNING),
        ({"telephony_provider": "azure"}, "provider.selection", Status.BLOCKED),
        ({"stt_provider": "simulator"}, "provider.selection", Status.BLOCKED),
    ],
)
async def test_twilio_configuration_problems_are_reported_with_the_right_severity(overrides, ident, status):
    report = await run_doctor(twilio_settings(**overrides), providers=("twilio",))
    check = by_id(report)[ident]
    assert check.status is status, check.detail
    assert TWILIO_TOKEN not in report.render_text()


async def test_every_twilio_online_check_can_pass_and_credentials_go_only_to_twilio(sqlite_url):
    seen: list[httpx.Request] = []
    report = await twilio_report(sqlite_url, seen=seen)
    checks = by_id(report)
    for ident in (
        "twilio_callback.health",
        "twilio_callback.ready",
        "twilio_callback.webhook_auth",
        "twilio_callback.media_auth",
        "twilio.account",
        "twilio.number",
        "speech.token",
    ):
        assert checks[ident].status is Status.PASS, (ident, checks[ident].detail)
    assert checks["twilio_callback.external"].status is Status.UNVERIFIED and not report.blocked
    basic = {r.url.host for r in seen if r.headers.get("authorization", "").startswith("Basic ")}
    assert basic == {"api.twilio.com"}  # the account credentials are never sent to the callback host
    assert all(r.method == "GET" or "twilio/voice" in str(r.url) or "issueToken" in str(r.url) for r in seen)
    assert TWILIO_TOKEN not in report.render_text() + report.render_json()


async def test_a_trial_account_is_blocked_because_twilio_strips_stream_and_dial(sqlite_url):
    trial = httpx.Response(200, json={"status": "active", "type": "Trial"})
    check = by_id(await twilio_report(sqlite_url, {TWILIO_ACCOUNT_URL: trial}))["twilio.account"]
    assert check.status is Status.BLOCKED and "TRIAL" in check.detail and "<Stream>" in check.detail
    suspended = httpx.Response(200, json={"status": "suspended", "type": "Full"})
    assert by_id(await twilio_report(sqlite_url, {TWILIO_ACCOUNT_URL: suspended}))["twilio.account"].status is (
        Status.BLOCKED
    )


async def test_rejected_credentials_stop_the_twilio_checks_there(sqlite_url):
    seen: list[httpx.Request] = []
    report = await twilio_report(sqlite_url, {TWILIO_ACCOUNT_URL: httpx.Response(401)}, seen)
    checks = by_id(report)
    assert checks["twilio.account"].status is Status.BLOCKED and "rejected" in checks["twilio.account"].detail
    assert "twilio.number" not in checks and not any("IncomingPhoneNumbers" in str(r.url) for r in seen)


@pytest.mark.parametrize(
    ("row", "needle"),
    [
        ({"voice_url": "https://other.example.net/hook?token=SECRETVALUE"}, "other.example.net"),
        ({"voice_url": VOICE_URL + "/extra"}, HOST),
        ({"voice_url": "http://" + HOST + "/api/v1/webhooks/twilio/voice"}, HOST),
        ({"voice_url": ""}, "no voice URL"),
        ({"voice_method": "GET"}, "GET"),
        ({"voice_application_sid": "AP" + "0" * 32}, "TwiML application"),
    ],
)
async def test_a_number_that_does_not_send_calls_here_is_blocked_without_echoing_its_url(sqlite_url, row, needle):
    numbers = httpx.Response(200, json={"incoming_phone_numbers": [{**NUMBER_ROW, **row}]})
    report = await twilio_report(sqlite_url, {TWILIO_NUMBERS_URL: numbers})
    check = by_id(report)["twilio.number"]
    assert check.status is Status.BLOCKED and needle in check.detail, check.detail
    assert "SECRETVALUE" not in report.render_text() and NUMBER not in report.render_text()


async def test_an_account_without_the_configured_number_is_blocked(sqlite_url):
    empty = httpx.Response(200, json={"incoming_phone_numbers": []})
    check = by_id(await twilio_report(sqlite_url, {TWILIO_NUMBERS_URL: empty}))["twilio.number"]
    assert check.status is Status.BLOCKED and "no matching phone number" in check.detail


async def test_an_unsigned_twilio_request_being_accepted_is_blocked(sqlite_url):
    voice = f"POST https://{HOST}/api/v1/webhooks/twilio/voice"
    media = f"GET https://{HOST}/api/v1/media/twilio/doctorprobe"
    report = await twilio_report(sqlite_url, {voice: httpx.Response(200), media: httpx.Response(101)})
    checks = by_id(report)
    assert checks["twilio_callback.webhook_auth"].status is Status.BLOCKED
    assert "UNSIGNED" in checks["twilio_callback.webhook_auth"].detail
    assert checks["twilio_callback.media_auth"].status is Status.BLOCKED
    missing = await twilio_report(sqlite_url, {voice: httpx.Response(404)})
    assert "SPARTA_TELEPHONY_PROVIDER" in by_id(missing)["twilio_callback.webhook_auth"].detail


# -------------------------------------------------------------------------------------------------------- CLI
def test_the_command_prints_json_and_exits_nonzero_when_blocked(monkeypatch, capsys):
    for name in ("SPARTA_TELEPHONY_PROVIDER", "SPARTA_STT_PROVIDER", "SPARTA_TTS_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir("/")  # no .env to pick up
    assert cli.main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["BLOCKED"] > 0 and payload["online"] is False


def test_the_command_rejects_an_unknown_provider(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--provider", "plivo"])
    assert caught.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_the_command_exits_zero_when_nothing_is_blocked(monkeypatch, capsys):
    values = {
        "SPARTA_ENV": "test",
        "SPARTA_TELEPHONY_PROVIDER": "azure",
        "SPARTA_STT_PROVIDER": "azure",
        "SPARTA_TTS_PROVIDER": "azure",
        "SPARTA_ACS_CONNECTION_STRING": f"endpoint=https://sparta-test.communication.azure.com/;accesskey={ACS_KEY}",
        "SPARTA_ACS_CALLBACK_BASE_URL": f"https://{HOST}",
        "SPARTA_ACS_RESOURCE_ID": "11111111-2222-3333-4444-555555555555",
        "SPARTA_ENTRA_TENANT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "SPARTA_EVENT_GRID_AUDIENCE": "api://sparta-event-grid",
        "SPARTA_AZURE_SPEECH_KEY": SPEECH_KEY,
        "SPARTA_AZURE_SPEECH_REGION": "centralindia",
        "SPARTA_TRUSTED_HOSTS": HOST,
        "SPARTA_AUTH_MODE": "oidc",
        "SPARTA_OIDC_ISSUER": "https://login.example.com/",
        "SPARTA_OIDC_AUDIENCE": "api://sparta",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir("/")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Verdict: NO BLOCKERS FOUND" in out and SPEECH_KEY not in out and ACS_KEY not in out
