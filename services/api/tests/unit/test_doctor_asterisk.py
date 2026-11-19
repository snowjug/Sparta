"""``sparta doctor --provider asterisk``: the free local-SIP path.

The doctor must say what it checked and what it could not, must never print the callback secret or a credential found in a
configuration file, and must not mistake a green configuration for a working phone. The configuration files, the SIP
service and the media listener are all faked here (fixture text parsed in memory or written to a temporary directory,
throwaway sockets): nothing needs Asterisk, Docker, a speech model or the network.
"""

import asyncio
import contextlib
import dataclasses
import json
import socket
import sys
import threading
import types
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from sparta import cli
from sparta.config import Settings
from sparta.db.models import Base
from sparta.db.session import Database
from sparta.doctor import Status, run_doctor
from sparta.doctor import asterisk as ast
from sparta.doctor import asterisk_conf as conf
from sparta.doctor import asterisk_online as probes
from sparta.doctor.model import Check, DoctorReport, _plain
from sparta.doctor.runner import normalise_providers, unverified_checks

SECRET = "Zq9-sentinel-callback-secret_ABCDEFGHIJ0123456789"
CONFIG_ID = "asterisk.config."
REAL_FIND_DIRECTORY = conf.find_directory  # the autouse fixture below replaces it for every test that is not about it
SHIPPED = Path(__file__).resolve().parents[4] / "infrastructure" / "asterisk"

# ------------------------------------------------------------------------------------------- fixture configuration
DIALPLAN = """\
; Sparta local-SIP dialplan. A comment may mention Dial(PJSIP/${EXTEN}) without it being one.
[general]
static = yes

[globals]
MAXCALLS = ${ENV(ASTERISK_MAX_CALLS)}
MAXSECS = ${ENV(ASTERISK_MAX_CALL_SECONDS)}
SPARTA_URL = http://${ENV(SPARTA_API_HOST)}:${ENV(SPARTA_API_PORT)}/api/v1/webhooks/asterisk

[from-sparta-sip]
exten => 6000,1,Set(SPARTA_CALL=0)
 same => n,Set(GROUP()=sparta)
 same => n,GotoIf($[${GROUP_COUNT(sparta)} > ${MAXCALLS}]?busy)
 same => n,Set(TIMEOUT(absolute)=${MAXSECS})
 same => n,Set(CURLOPT(userpwd)=asterisk:${ENV(SPARTA_WEBHOOK_SECRET)})
 same => n,Set(REPLY=${CURL(${SPARTA_URL}/incoming,channel=${UNIQUEID}&exten=${EXTEN})})
 same => n(busy),Busy(5)
 same => n,AudioSocket(${MEDIA_ID},${SPARTA_MEDIA})
 same => n(takeover),Dial(PJSIP/6002,30,r)
 same => n,Hangup()
exten => _X.,1,Hangup(1)
exten => i,1,Hangup(1)
exten => h,1,NoOp()
"""

PJSIP = """\
[global]
type = global
endpoint_identifier_order = username

[sparta-phone](!)
type = endpoint
context = from-sparta-sip
disallow = all
; G.711 only
allow = ulaw
allow = alaw
identify_by = username
allow_transfer = no
allow_unauthenticated_options = no

[6001](sparta-phone)
auth = auth6001
aors = 6001

[auth6001]
type = auth
auth_type = userpass
username = 6001
password = @@SIP_PASSWORD_6001@@

[6001]
type = aor
max_contacts = 1

[6002](sparta-phone)
auth = auth6002
aors = 6002

[auth6002]
type = auth
auth_type = userpass
username = 6002
password = @@SIP_PASSWORD_6002@@

[6002]
type = aor
max_contacts = 1
"""

LOADED = [
    "res_pjproject",
    "res_pjsip",
    "res_pjsip_session",
    "chan_pjsip",
    "res_rtp_asterisk",
    "codec_ulaw",
    "codec_alaw",
    "pbx_config",
    "app_dial",
    "res_audiosocket",
    "app_audiosocket",
    "res_curl",
    "func_curl",
    "func_timeout",
    "func_groupcount",
    "func_strings",
    "func_uri",
]
MODULES = "[modules]\nautoload = no\n" + "".join(f"load = {name}.so\n" for name in LOADED) + "noload = res_ari.so\n"
FILES = {
    "extensions.conf": DIALPLAN,
    "pjsip.conf.template": PJSIP,
    "rtp.conf": "[general]\nrtpstart = 10000\nrtpend = 10019\n",
    "modules.conf": MODULES,
    "http.conf": "[general]\nenabled = no\n",
    "manager.conf": "[general]\nenabled = no\n",
    "asterisk.conf": "[options]\nverbose = 0\ndebug = 0\n",
    "logger.conf": "[logfiles]\nconsole => notice,warning,error\n",
}


def _texts(changes: dict[str, str | None]) -> dict[str, str]:
    """The fixture files with ``changes`` applied: a key is a file name with ``_`` for ``.`` (``extensions_conf``)."""
    texts = dict(FILES)
    for key, value in changes.items():
        name = key.replace("_conf_template", ".conf.template").replace("_conf", ".conf")
        if value is None:
            texts.pop(name, None)
        else:
            texts[name] = value
    return texts


def write_config(tmp_path: Path, **changes: str | None) -> Path:
    directory = tmp_path / "asterisk"
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in _texts(changes).items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def memory_files(**changes: str | None) -> conf.ConfigFiles:
    """The same files, parsed straight from text: most tests need no disk."""
    texts = _texts(changes)
    found: dict[str, conf.ConfigFile] = {}
    for logical, names in conf.FILES.items():
        for name in names:
            if name in texts:
                found[logical] = conf.ConfigFile(name, tuple(conf.parse_conf(texts[name])))
                break
    return conf.ConfigFiles(True, found)


def config_check(ident: str, settings: Settings | None = None, **changes: str | None) -> Check:
    checks = ast.config_checks(settings or settings_for(), memory_files(**changes))
    return {check.id: check for check in checks}[CONFIG_ID + ident]


def mutate(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


# ------------------------------------------------------------------------------------------------------- helpers
@dataclasses.dataclass(frozen=True)
class Model:
    """The shape of ``sparta.providers.local_models.ModelStatus`` that the doctor reads."""

    name: str
    kind: str
    installed: bool = True
    verified: bool | None = True
    selected: bool = True
    locale: str | None = None


READY = [
    Model("small", "stt"),
    Model("en_US-ljspeech-medium", "tts", locale="en-IN"),
    Model("hi_IN-priyamvada-medium", "tts", locale="hi-IN"),
    Model("kn_IN-syspin_male-medium", "tts", locale="kn-IN"),
    Model("large-v3-turbo", "stt", installed=False, verified=None, selected=False),
]


def models_module(statuses: object) -> types.ModuleType:
    module = types.ModuleType("sparta.providers.local_models")
    module.model_status = lambda settings, *, verify=False, root=None: statuses  # type: ignore[attr-defined]
    return module


def settings_for(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "telephony_provider": "asterisk",
        "stt_provider": "local",
        "tts_provider": "local",
        "asterisk_webhook_secret": SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def by_id(report: DoctorReport) -> dict[str, Check]:
    return {check.id: check for check in report.checks}


def everything(report: DoctorReport) -> str:
    return report.render_text() + report.render_json() + report.render_text(colour=True)


def rendered(*checks: Check) -> str:
    report = DoctorReport()
    report.extend(list(checks))
    return everything(report)


async def doctor(settings: Settings | None = None, directory: Path | None = None, **kwargs: object) -> DoctorReport:
    return await run_doctor(
        settings or settings_for(),
        providers=("asterisk",),
        asterisk_dir=directory,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """No repository files, speech engines or models are needed (or read): they are all stood in for unless a test says."""
    monkeypatch.setattr(
        conf, "find_directory", lambda explicit=None: explicit if explicit is not None and explicit.is_dir() else None
    )
    monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
    monkeypatch.setitem(sys.modules, "piper", types.ModuleType("piper"))
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", models_module(READY))
    monkeypatch.setattr(
        ast, "speech_sdk_check", lambda settings: Check("speech.sdk", "Azure Speech", "sdk", Status.PASS)
    )


@pytest.fixture
async def sqlite_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'doctor.db').as_posix()}"
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await database.dispose()
    return url


# ------------------------------------------------------------------------------------------------------ the whole
async def test_a_complete_local_sip_configuration_has_no_blocker_and_says_what_is_unproven(tmp_path):
    report = await doctor(directory=write_config(tmp_path))
    checks = by_id(report)
    assert not report.blocked, [(x.id, x.detail) for x in report.checks if x.status is Status.BLOCKED]
    assert report.exit_code() == 0
    for ident in (
        "asterisk.provider",
        "asterisk.callback_secret",
        "asterisk.media_peers",
        "asterisk.extensions",
        "asterisk.limits",
        "asterisk.speech",
        "asterisk.local_stt",
        "asterisk.local_tts",
        "asterisk.local_models",
        "media.format",
        *(
            CONFIG_ID + name
            for name in (
                "files",
                "no_pstn",
                "pjsip",
                "credentials",
                "control_plane",
                "modules",
                "logging",
                "extensions",
                "call_limits",
            )
        ),
    ):
        assert checks[ident].status is Status.PASS, (ident, checks[ident].detail)
    # a green report is never described as a working phone line, and the ACS / Twilio / PSTN items do not appear
    for ident in ("live.sip_call", "live.barge_in", "live.recognition_quality", "live.takeover", "legal.review"):
        assert checks[ident].status is Status.UNVERIFIED
    assert "live.pstn_inbound" not in checks and "doctor.scope" not in checks
    assert not any(ident.startswith(("acs.", "twilio.", "speech.")) for ident in checks)
    assert "cannot be proven" in report.verdict()
    assert "not a phone-number connection" in checks["live.sip_call"].detail
    assert "Asterisk (local SIP telephony)" in report.render_text()
    assert SECRET not in everything(report) and "the value is not shown" in checks["asterisk.callback_secret"].detail


async def test_the_default_configuration_is_blocked_on_the_secret_and_the_speech_and_says_why():
    report = await run_doctor(Settings(_env_file=None), providers=("asterisk",))
    checks = by_id(report)
    assert report.blocked and report.exit_code() == 1
    assert checks["asterisk.provider"].status is Status.WARNING
    assert checks["asterisk.callback_secret"].status is Status.BLOCKED
    assert checks["asterisk.speech"].status is Status.BLOCKED
    assert "NOT READY" in report.render_text()
    assert json.loads(report.render_json())["providers"] == ["asterisk"]


async def test_the_provider_must_be_selected_but_the_other_checks_still_run(tmp_path):
    report = await doctor(settings_for(telephony_provider="azure"), write_config(tmp_path))
    checks = by_id(report)
    assert checks["asterisk.provider"].status is Status.WARNING
    assert "SPARTA_TELEPHONY_PROVIDER=asterisk" in checks["asterisk.provider"].fix
    assert checks["asterisk.callback_secret"].status is Status.PASS and not report.blocked


async def test_a_leftover_acs_url_is_not_judged_when_the_provider_is_asterisk():
    report = await doctor(settings_for(acs_callback_base_url="https://sparta.example.com"))
    assert by_id(report)["core.auth"].status is Status.WARNING  # not "development identity on a public URL"


# ------------------------------------------------------------------------------------------------------- secret
@pytest.mark.parametrize(
    ("changes", "status", "needle"),
    [
        ({"asterisk_webhook_secret": None}, Status.BLOCKED, "absent"),
        ({"asterisk_webhook_secret": "short-secret"}, Status.BLOCKED, "too short"),
        ({"asterisk_webhook_secret": "a" * 23}, Status.BLOCKED, "too short"),
        ({"asterisk_webhook_secret": "a" * 24}, Status.PASS, "present"),
        ({"asterisk_webhook_secret": "   "}, Status.BLOCKED, "empty"),
        ({"asterisk_webhook_secret": "a" * 24 + "!:@/="}, Status.WARNING, "refuses to start"),
    ],
)
def test_the_callback_secret_is_present_long_enough_and_never_shown(changes, status, needle):
    check = ast.secret_check(settings_for(**changes))
    assert check.status is status and needle in check.detail, check.detail
    if status is Status.BLOCKED:
        assert "secrets.token_urlsafe(32)" in check.fix  # how to make one, never one made here
    for value in changes.values():
        if value and len(value) > 8:
            assert value not in rendered(check)


def test_the_secret_may_come_from_a_mounted_file(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text(SECRET + "\nignored second line\n", encoding="utf-8")
    ok = ast.secret_check(settings_for(asterisk_webhook_secret=None, asterisk_webhook_secret_file=str(path)))
    assert ok.status is Status.PASS
    assert SECRET not in rendered(ok) and "ignored second line" not in rendered(ok)
    missing = ast.secret_check(
        settings_for(asterisk_webhook_secret=None, asterisk_webhook_secret_file=str(tmp_path / "missing.txt"))
    )
    assert missing.status is Status.BLOCKED and "cannot be read" in missing.detail
    path.write_text("", encoding="utf-8")
    assert (
        ast.secret_check(settings_for(asterisk_webhook_secret=None, asterisk_webhook_secret_file=str(path))).status
        is Status.BLOCKED
    )


# -------------------------------------------------------------------------------------------------- media peers
@pytest.mark.parametrize(
    ("peers", "bind", "status", "needle"),
    [
        (None, "127.0.0.1", Status.PASS, "peer(s) allowed"),
        (["asterisk"], "0.0.0.0", Status.PASS, "1 host names"),
        (["172.18.0.0/16"], "0.0.0.0", Status.PASS, "1 address or range"),
        (["127.0.0.1", "::1"], "0.0.0.0", Status.WARNING, "only loopback peers"),
        (["127.0.0.1"], "192.168.1.20", Status.WARNING, "only loopback peers"),
        (["10.0.0.0/8"], "0.0.0.0", Status.WARNING, "very wide range (/8)"),
        (["2001:db8::/32"], "::", Status.WARNING, "very wide range (/32)"),
        (
            ["10.0.0.0/8"],
            "127.0.0.1",
            Status.PASS,
            "peer(s) allowed",
        ),  # nothing outside this machine can connect anyway
        (["0.0.0.0/0"], "127.0.0.1", Status.BLOCKED, "would allow every address"),
        (["::/0"], "0.0.0.0", Status.BLOCKED, "would allow every address"),
        (["asterisk", "bad entry!"], "127.0.0.1", Status.BLOCKED, "entry 2"),
        ([], "127.0.0.1", Status.BLOCKED, "no peer is allowed"),
    ],
)
def test_media_peers_must_be_valid_narrow_and_able_to_reach_the_listener(peers, bind, status, needle):
    overrides: dict[str, object] = {"asterisk_media_bind": bind}
    if peers is not None:
        overrides["asterisk_media_peers"] = peers
    check = ast.peers_check(settings_for(**overrides))
    assert check.status is status and needle in check.detail, check.detail
    assert "bad entry!" not in rendered(check)  # an entry that is not valid is not echoed back


def test_the_listener_address_and_port_are_shown_readably():
    check = ast.peers_check(settings_for(asterisk_media_port=8090)).safe()
    assert "127.0.0.1:8090" in check.detail  # the redaction would otherwise turn both numbers into [digits]/[phone]


# --------------------------------------------------------------------------------------------- extensions, limits
def test_extensions_must_be_digits_and_differ():
    good = ast.extensions_check(settings_for())
    assert good.status is Status.PASS and "extension 6000" in good.detail and "extension 6002" in good.detail
    same = ast.extensions_check(settings_for(asterisk_extension="6000", asterisk_owner_extension="6000"))
    assert same.status is Status.BLOCKED and "must differ" in same.detail
    broken = settings_for().model_copy(update={"asterisk_extension": "60x0"})  # the setting itself rejects this
    assert ast.extensions_check(broken).status is Status.BLOCKED


@pytest.mark.parametrize(
    ("changes", "status", "needle"),
    [
        ({}, Status.PASS, "at most 5 call(s) at once, 600 s per call, 240 call-minutes"),
        ({"max_active_calls": 0}, Status.WARNING, "below 1"),
        ({"max_active_calls": 11, "asterisk_max_media_connections": 16}, Status.WARNING, "above 10"),
        ({"max_active_calls": 10, "asterisk_max_media_connections": 16}, Status.PASS, "at most 10 call(s)"),
        ({"max_active_calls": 9}, Status.WARNING, "SPARTA_ASTERISK_MAX_MEDIA_CONNECTIONS (8)"),
        ({"max_call_duration_s": 1801}, Status.WARNING, "above 1800 seconds"),
        ({"max_call_duration_s": 1800}, Status.PASS, "1800 s per call"),
        ({"daily_call_minutes_cap": 0}, Status.PASS, "no minute limit"),
    ],
)
def test_call_limits_are_reported_with_their_numbers(changes, status, needle):
    check = ast.limits_check(settings_for(**changes))
    assert check.status is status and needle in check.safe().detail, check.detail
    assert "[digits]" not in check.safe().detail  # 1800 and 1801 stay readable


# ------------------------------------------------------------------------------------------------------- speech
@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"stt_provider": "simulator"}, "speech recognition (SPARTA_STT_PROVIDER) is the simulator"),
        ({"tts_provider": "simulator"}, "speech synthesis (SPARTA_TTS_PROVIDER) is the simulator"),
        ({"stt_provider": "fake"}, "'fake', which is test-only"),
        ({"tts_provider": "fake"}, "'fake', which is test-only (tones, not speech)"),
    ],
)
def test_a_live_call_needs_real_speech_so_the_simulator_and_fake_are_blocked(changes, needle):
    check = ast.speech_selection_check(settings_for(**changes))
    assert check.status is Status.BLOCKED and needle in check.detail
    assert "SPARTA_STT_PROVIDER=local" in check.fix


def names(checks: list[Check]) -> set[str]:
    return {check.id for check in checks}


def test_azure_speech_selected_for_asterisk_reuses_the_existing_azure_checks():
    checks = {c.id: c for c in ast.speech_checks_for(settings_for(stt_provider="azure", tts_provider="azure"))}
    assert checks["asterisk.speech"].status is Status.PASS
    assert checks["speech.credentials"].status is Status.BLOCKED  # no key configured
    assert "speech.sdk" in checks and "asterisk.local_stt" not in checks and "asterisk.local_models" not in checks


def test_local_speech_does_not_ask_for_azure_credentials():
    assert names(ast.speech_checks_for(settings_for())) == {
        "asterisk.speech",
        "asterisk.local_stt",
        "asterisk.local_tts",
        "asterisk.local_models",
    }


def test_missing_local_engines_are_unverified_with_the_extra_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "piper", None)
    checks = {c.id: c for c in ast.speech_checks_for(settings_for())}
    for ident in ("asterisk.local_stt", "asterisk.local_tts"):
        assert checks[ident].status is Status.UNVERIFIED
        assert "pip install 'sparta-api[local-speech]'" in checks[ident].fix
    only_tts = names(ast.speech_checks_for(settings_for(stt_provider="azure")))
    assert "asterisk.local_stt" not in only_tts and "asterisk.local_tts" in only_tts


def test_an_engine_that_imports_with_an_error_is_unverified_not_a_crash(monkeypatch):
    real = ast.importlib.import_module

    def broken(name: str, package: str | None = None) -> types.ModuleType:
        if name == "piper":
            raise RuntimeError("DLL load failed at C:\\secret\\path")
        return real(name, package)

    monkeypatch.setattr(ast.importlib, "import_module", broken)
    checks = ast.speech_checks_for(settings_for())
    check = {c.id: c for c in checks}["asterisk.local_tts"]
    assert check.status is Status.UNVERIFIED and "RuntimeError" in check.detail
    shown = rendered(*checks)
    assert "DLL load failed" not in shown and "\\secret\\path" not in shown and "C:" not in shown  # no exception text


# -------------------------------------------------------------------------------------------------- local models
def test_models_that_are_installed_and_verified_pass():
    check = ast.local_models_check(settings_for())
    assert check is not None and check.status is Status.PASS
    assert "speech recognition model small: installed, SHA-256 verified" in check.detail
    assert "voice hi_IN-priyamvada-medium (hi-IN): installed, SHA-256 verified" in check.detail
    assert "large-v3-turbo" not in check.detail  # only what the settings select is judged


@pytest.mark.parametrize(
    ("statuses", "status", "needle"),
    [
        (
            [Model("small", "stt", installed=False, verified=None), *READY[1:4]],
            Status.BLOCKED,
            "model small: not installed",
        ),
        (
            [
                READY[0],
                Model("en_US-ljspeech-medium", "tts", locale="en-IN"),
                Model("hi_IN-p", "tts", False, None, locale="hi-IN"),
            ],
            Status.WARNING,
            "voice hi_IN-p (hi-IN): not installed",
        ),
        (
            [READY[0], Model("en_US-ljspeech-medium", "tts", False, None, locale="en-IN")],
            Status.BLOCKED,
            "voice en_US-ljspeech-medium (en-IN): not installed",
        ),
        ([Model("small", "stt", verified=False), *READY[1:4]], Status.BLOCKED, "CORRUPT"),
        ([Model("small", "stt", verified=None), *READY[1:4]], Status.UNVERIFIED, "not hash-checked"),
        ([READY[0]], Status.BLOCKED, "no model or voice is selected"),
    ],
)
def test_models_that_are_missing_corrupt_or_unchecked_are_reported_by_what_they_do_to_a_call(
    monkeypatch, statuses, status, needle
):
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", models_module(statuses))
    check = ast.local_models_check(settings_for())
    assert check is not None and check.status is status and needle in check.detail, check
    assert "python -m sparta models fetch" in check.fix


@pytest.mark.parametrize("unusable", [None, "not a list", {"small": True}, [object()], []])
def test_a_model_check_that_cannot_be_read_is_unverified(monkeypatch, unusable):
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", models_module(unusable))
    check = ast.local_models_check(settings_for())
    assert check is not None and check.status is Status.UNVERIFIED
    assert "local model check not available" in check.detail


def test_a_missing_model_module_or_a_model_check_that_raises_is_unverified(monkeypatch):
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", None)
    missing = ast.local_models_check(settings_for())
    assert missing is not None and missing.status is Status.UNVERIFIED
    assert "local model check not available" in missing.detail
    broken = types.ModuleType("sparta.providers.local_models")

    def explode(settings: Settings, *, verify: bool = False) -> list[Model]:
        raise PermissionError("C:\\private\\models")

    broken.model_status = explode  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", broken)
    raised = ast.local_models_check(settings_for())
    assert raised is not None and raised.status is Status.UNVERIFIED and "PermissionError" in raised.detail
    assert "private" not in rendered(raised)
    older = types.ModuleType("sparta.providers.local_models")
    older.model_status = lambda settings: READY  # type: ignore[attr-defined]  # a signature without verify still works
    monkeypatch.setitem(sys.modules, "sparta.providers.local_models", older)
    result = ast.local_models_check(settings_for())
    assert result is not None and result.status is Status.PASS


def test_the_real_model_manifest_reports_an_empty_model_directory_as_blocked(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "sparta.providers.local_models", raising=False)
    pytest.importorskip("sparta.providers.local_models")
    check = ast.local_models_check(settings_for(local_model_dir=str(tmp_path / "no-models")))
    assert check is not None and check.status is Status.BLOCKED
    assert "model small: not installed" in check.detail, check.detail
    assert str(tmp_path) not in rendered(check)  # no local path is printed


def test_nothing_is_said_about_local_models_when_speech_is_not_local():
    assert ast.local_models_check(settings_for(stt_provider="azure", tts_provider="azure")) is None


# ----------------------------------------------------------------------------------------- the configuration files
async def test_without_the_repository_files_the_static_checks_are_one_unverified_line():
    checks = by_id(await doctor())
    assert checks[CONFIG_ID + "files"].status is Status.UNVERIFIED
    assert "source checkout" in checks[CONFIG_ID + "files"].fix
    assert [ident for ident in checks if ident.startswith(CONFIG_ID)] == [CONFIG_ID + "files"]


def test_missing_files_make_only_the_checks_that_need_them_unverified():
    checks = {c.id: c for c in ast.config_checks(settings_for(), memory_files(pjsip_conf_template=None, rtp_conf=None))}
    assert checks[CONFIG_ID + "files"].status is Status.UNVERIFIED
    assert "pjsip.conf.template, rtp.conf" in checks[CONFIG_ID + "files"].detail
    assert checks[CONFIG_ID + "pjsip"].status is Status.UNVERIFIED
    assert checks[CONFIG_ID + "no_pstn"].status is Status.UNVERIFIED  # the dialplan alone cannot rule out a trunk
    assert checks[CONFIG_ID + "call_limits"].status is Status.PASS


async def test_an_unreadable_or_oversized_file_is_unverified_not_a_crash(tmp_path):
    directory = write_config(tmp_path)
    (directory / "rtp.conf").write_text("; " + "x" * (conf.MAX_FILE_BYTES + 1), encoding="utf-8")
    check = by_id(await doctor(directory=directory))[CONFIG_ID + "files"]
    assert check.status is Status.UNVERIFIED and "cannot be read" in check.detail and "rtp.conf" in check.detail
    assert "not found" not in check.detail  # a file that exists is not also reported missing


DIAL_CASES = [
    ("exten => _X.,1,Dial(PJSIP/trunk/${EXTEN})", Status.BLOCKED),
    ("exten => _+.,1,Dial(PJSIP/${EXTEN}@provider)", Status.BLOCKED),
    ("exten => _X.,1,Dial(PJSIP/${EXTEN})", Status.BLOCKED),
    ("exten => _XXXX,1,Dial(SIP/provider/${EXTEN})", Status.BLOCKED),
    ("exten => 6000,2,Dial(Local/${EXTEN}@outbound)", Status.BLOCKED),
    ('exten => 6000,2,ExecIf($["${X}" = "1"]?Dial(PJSIP/${EXTEN}@trunk))', Status.BLOCKED),
    ("exten => 6000,2,Originate(PJSIP/${CALLERID(num)}@carrier,app,Echo)", Status.BLOCKED),
    ("exten => 6000,2,Dial(PJSIP/${ARG1})", Status.BLOCKED),
    ("exten => 6000,2,dial(sip/provider/${EXTEN})", Status.BLOCKED),  # applications and channel names ignore case
    ("exten => 6000,2,Dial(PJSIP/${NEXT_TARGET},30)", Status.WARNING),
    ("exten => 6000,2,Dial(PJSIP/6003)", Status.WARNING),
    ("exten => 6000,2,Dial(PJSIP/office)", Status.WARNING),
    ("exten => 6001,1,Dial(PJSIP/${EXTEN})", Status.PASS),  # EXTEN is the literal local extension itself
    ("exten => _X.,1,Dial(PJSIP/6002)", Status.PASS),  # a fixed local target is not a way out
    ("exten => 6000,2,Dial(pjsip/6002&PJSIP/6001,20)", Status.PASS),
    ("exten => _X.,1,Hangup(1)", Status.PASS),
    (";exten => _X.,1,Dial(PJSIP/trunk/${EXTEN})", Status.PASS),  # commented out
    (";-- exten => _X.,1,Dial(PJSIP/trunk/${EXTEN})\nexten => 6000,2,NoOp()\n--;", Status.PASS),  # in a comment block
]


@pytest.mark.parametrize(("lines", "status"), DIAL_CASES)
def test_a_route_out_of_the_local_extensions_is_blocked(lines, status):
    check = config_check("no_pstn", extensions_conf=DIALPLAN + lines + "\n")
    assert check.status is status, (lines, check.detail)
    if status is not Status.PASS:
        assert "extensions.conf line" in check.detail and "${" not in check.detail  # a line number, never the line


@pytest.mark.parametrize(
    "addition",
    [
        "\n[provider-registration]\ntype = registration\nserver_uri = sip:example.invalid\nclient_uri = sip:me@example.invalid\n",
        "\n[carrier-match]\ntype = identify\nendpoint = 6001\nmatch = 192.0.2.10\n",
        "\n[trunk]\ntype = endpoint\ncontext = from-sparta-sip\nauth = auth6001\n",
        "\n[extra](sparta-phone)\nauth = auth6001\noutbound_auth = auth6001\n",
    ],
)
def test_a_trunk_registration_or_source_address_match_in_the_sip_configuration_is_blocked(addition):
    check = config_check("no_pstn", pjsip_conf_template=PJSIP + addition)
    assert check.status is Status.BLOCKED and "pjsip.conf.template line" in check.detail, check.detail


def test_the_safe_configuration_has_no_route_out_and_says_local_sip_is_not_the_phone_network():
    check = config_check("no_pstn")
    assert check.status is Status.PASS and "no outbound or PSTN route" in check.detail
    assert "not a phone-number connection" in check.detail


def test_many_findings_are_listed_by_line_number_without_the_lines_themselves():
    many = "".join(f"exten => _{n}X.,1,Dial(PJSIP/trunk/${{EXTEN}})\n" for n in range(1, 9))
    check = config_check("no_pstn", extensions_conf=DIALPLAN + many)
    assert check.status is Status.BLOCKED and check.detail.count("extensions.conf line") == 5
    assert "and 3 more" in check.detail and "${" not in check.detail and "_1X." not in check.detail


PJSIP_CASES = [
    (mutate(PJSIP, "auth = auth6001\n", ""), Status.BLOCKED, "without auth"),
    (PJSIP + "\n[anonymous]\ntype = endpoint\nauth = auth6001\n", Status.BLOCKED, "named anonymous"),
    (mutate(PJSIP, "identify_by = username", "identify_by = ip,username"), Status.BLOCKED, "identify_by matches"),
    (mutate(PJSIP, "identify_by = username", "identify_by = auth_username"), Status.WARNING, "identify_by matches"),
    (mutate(PJSIP, "identify_by = username\n", ""), Status.WARNING, "identify_by is not set"),
    (mutate(PJSIP, "allow = alaw\n", "allow = alaw\nallow = g722\n"), Status.WARNING, "not exactly ulaw and alaw"),
    (mutate(PJSIP, "allow = alaw\n", ""), Status.WARNING, "not exactly ulaw and alaw"),
    (
        mutate(PJSIP, "disallow = all\n", "allow = ulaw\ndisallow = all\n"),
        Status.WARNING,
        "allow comes before disallow",
    ),
    (mutate(PJSIP, "disallow = all\n", ""), Status.WARNING, "allow comes before disallow"),
    (mutate(PJSIP, "disallow = all", "disallow = all\nallow = !all,ulaw,alaw,opus\ndisallow = opus"), Status.PASS, ""),
    (
        mutate(PJSIP, "allow_unauthenticated_options = no", "allow_unauthenticated_options = yes"),
        Status.BLOCKED,
        "OPTIONS",
    ),
    (mutate(PJSIP, "allow_unauthenticated_options = no\n", ""), Status.WARNING, "not written anywhere"),
    (mutate(PJSIP, "allow_transfer = no", "allow_transfer = yes"), Status.WARNING, "SIP transfer"),
    (
        mutate(PJSIP, "endpoint_identifier_order = username", "endpoint_identifier_order = ip,username"),
        Status.WARNING,
        "more than",
    ),
]


@pytest.mark.parametrize(("text", "status", "needle"), PJSIP_CASES)
def test_sip_endpoints_must_authenticate_match_by_user_name_and_allow_only_g711(text, status, needle):
    check = config_check("pjsip", pjsip_conf_template=text)
    assert check.status is status and needle in check.detail, check.detail


def test_endpoints_inherit_from_templates_and_a_template_alone_is_judged_without_auth():
    blocks = PJSIP.split("\n\n")
    only_template = "\n".join(b for b in blocks if "[6001]" not in b and "[6002]" not in b and "auth600" not in b)
    check = config_check("pjsip", pjsip_conf_template=only_template)
    assert check.status is Status.PASS and "1 endpoint(s)" in check.detail, check.detail
    assert config_check("pjsip", pjsip_conf_template="[global]\ntype = global\n").status is Status.UNVERIFIED
    assert config_check("pjsip").status is Status.PASS and "2 endpoint(s)" in config_check("pjsip").detail


@pytest.mark.parametrize(
    "password",
    [
        "@@SIP_PASSWORD_6001@@",
        "${SIP_PASSWORD_6001}",
        "@SIP_PASSWORD_6001@",
        "$SIP_PASSWORD_6001",
        "${ENV(SIP_PASSWORD_6001)}",
        "",
    ],
)
def test_a_placeholder_is_not_a_committed_credential(password):
    check = config_check("credentials", pjsip_conf_template=mutate(PJSIP, "@@SIP_PASSWORD_6001@@", password))
    assert check.status is Status.PASS, check.detail


@pytest.mark.parametrize(
    "password",
    ["hunter2-literal-value", "${SIP_PASSWORD_6001:-changeme-fallback}", "prefix-@@SIP_PASSWORD_6001@@", "12345678"],
)
def test_a_literal_credential_in_the_sip_template_is_blocked_and_never_echoed(password):
    check = config_check("credentials", pjsip_conf_template=mutate(PJSIP, "@@SIP_PASSWORD_6001@@", password))
    assert check.status is Status.BLOCKED and "pjsip.conf.template line" in check.detail, check.detail
    shown = rendered(check)
    for needle in ("hunter2-literal-value", "changeme-fallback", "prefix-", "12345678"):
        assert needle not in shown


@pytest.mark.parametrize(
    ("line", "literal"),
    [
        ("same => n,Set(CURLOPT(userpwd)=asterisk:plain-text-callback-secret)", True),
        ("same => n,Set(CURLOPT(userpwd)=asterisk:${ENV(SPARTA_WEBHOOK_SECRET)})", False),
        ("same => n,Set(CURLOPT(httpheader)=Authorization: Basic YXN0ZXJpc2s6bGl0ZXJhbA==)", True),
        ("same => n,Set(CURLOPT(httpheader)=Authorization: Bearer ${ENV(TOKEN)})", False),
        ("same => n,Set(DB_PASSWORD=plain-text-value)", True),
        ("same => n,Set(DB_PASSWORD=${ENV(DB_PASSWORD)})", False),
    ],
)
def test_a_literal_credential_in_the_dialplan_is_blocked_and_never_echoed(line, literal):
    check = config_check("credentials", extensions_conf=DIALPLAN + line + "\n")
    assert (check.status is Status.BLOCKED) is literal, check.detail
    for needle in ("plain-text", "YXN0ZXJpc2s6bGl0ZXJhbA"):
        assert needle not in rendered(check)


def test_a_literal_credential_in_the_globals_of_the_dialplan_is_blocked():
    text = mutate(DIALPLAN, "[globals]\n", "[globals]\nSIP_PASSWORD = plain-text-password\n")
    assert config_check("credentials", extensions_conf=text).status is Status.BLOCKED


@pytest.mark.parametrize(
    ("changes", "status", "needle"),
    [
        ({"http_conf": "[general]\nenabled = yes\n"}, Status.BLOCKED, "the HTTP server is enabled"),
        ({"manager_conf": "[general]\nenabled=true\n"}, Status.BLOCKED, "AMI is enabled"),
        ({"ari_conf_template": "[general]\nenabled = yes\n"}, Status.BLOCKED, "ARI is enabled"),
        ({"ari_conf_template": "[general]\nenabled = no\n"}, Status.PASS, "ari.conf.template"),
        (
            {"ari_conf_template": "[general]\npassword_format = plain\n"},
            Status.WARNING,
            "ARI is not explicitly disabled",
        ),
        ({"http_conf": None, "manager_conf": None}, Status.PASS, "not enabled in the repository files"),
    ],
)
def test_ari_ami_and_the_http_server_must_not_be_enabled(changes, status, needle):
    check = config_check("control_plane", **changes)
    assert check.status is status and needle in check.detail, check.detail


@pytest.mark.parametrize(
    ("modules", "status", "needle"),
    [
        (MODULES + "load = res_ari.so\n", Status.BLOCKED, "a module for ARI is loaded"),
        (MODULES + "load = res_pjsip_outbound_registration.so\n", Status.BLOCKED, "SIP trunks"),
        (MODULES + "load = app_system.so\n", Status.BLOCKED, "shell commands"),
        (MODULES + "load = app_voicemail.so\n", Status.WARNING, "features Sparta does not use"),
        (mutate(MODULES, "autoload = no", "autoload = yes"), Status.WARNING, "autoload is not switched off"),
        (mutate(MODULES, "load = res_audiosocket.so\n", ""), Status.BLOCKED, "res_audiosocket"),
        (mutate(MODULES, "load = func_timeout.so\n", ""), Status.BLOCKED, "func_timeout"),
        ("[modules]\nautoload = no\n", Status.BLOCKED, "modules a call needs are not loaded"),
    ],
)
def test_the_module_list_must_be_an_allow_list_of_what_a_local_call_needs(modules, status, needle):
    check = config_check("modules", modules_conf=modules)
    assert check.status is status and needle in check.detail, check.detail


@pytest.mark.parametrize(
    ("changes", "status", "needle"),
    [
        ({"asterisk_conf": "[options]\nverbose = 3\n"}, Status.BLOCKED, "verbose logging"),
        ({"asterisk_conf": "[options]\ndebug = 1\n"}, Status.BLOCKED, "debug logging"),
        ({"asterisk_conf": "[options]\nverbose = 2\ndebug = 0\n"}, Status.PASS, "verbose and debug logging are off"),
        (
            {"logger_conf": "[logfiles]\nconsole => notice,warning,error,verbose(3)\n"},
            Status.BLOCKED,
            "logger.conf line",
        ),
        ({"logger_conf": "[logfiles]\nfull => *\n"}, Status.BLOCKED, "logger.conf line"),
        ({"logger_conf": "[logfiles]\nconsole => debug\n"}, Status.BLOCKED, "logger.conf line"),
        ({"asterisk_conf": None, "logger_conf": None}, Status.UNVERIFIED, "neither asterisk.conf nor logger.conf"),
    ],
)
def test_verbose_logging_would_write_the_callback_secret_into_the_log(changes, status, needle):
    check = config_check("logging", **changes)
    assert check.status is status and needle in check.detail, check.detail


TIMEOUT_LINE = " same => n,Set(TIMEOUT(absolute)=${MAXSECS})\n"
GROUP_LINES = (" same => n,Set(GROUP()=sparta)\n", " same => n,GotoIf($[${GROUP_COUNT(sparta)} > ${MAXCALLS}]?busy)\n")


@pytest.mark.parametrize(
    ("removed", "status", "needle"),
    [
        ((TIMEOUT_LINE,), Status.WARNING, "no TIMEOUT(absolute)"),
        (GROUP_LINES, Status.WARNING, "no GROUP() limit"),
        ((TIMEOUT_LINE, *GROUP_LINES), Status.WARNING, "no TIMEOUT(absolute)"),
        ((GROUP_LINES[1],), Status.PASS, "GROUP()"),
    ],
)
def test_the_dialplan_should_limit_call_length_and_concurrency(removed, status, needle):
    text = DIALPLAN
    for line in removed:
        text = mutate(text, line, "")
    check = config_check("call_limits", extensions_conf=text)
    assert check.status is status and needle in check.detail, check.detail


def test_the_dialplan_and_the_settings_must_agree_on_the_extensions():
    moved = config_check("extensions", settings_for(asterisk_extension="7000"))
    assert moved.status is Status.WARNING and "defines no extension 7000" in moved.detail
    other_owner = config_check("extensions", settings_for(asterisk_owner_extension="6009"))
    assert other_owner.status is Status.WARNING and "never rings extension 6009" in other_owner.detail
    assert config_check("extensions").status is Status.PASS
    assert config_check("extensions", extensions_conf=None).status is Status.UNVERIFIED


@pytest.mark.skipif(not (SHIPPED / "extensions.conf").is_file(), reason="needs a source checkout")
async def test_the_asterisk_files_shipped_in_the_repository_pass_every_static_check():
    report = await doctor(directory=SHIPPED)
    problems = [
        (c.id, c.status.value, c.detail)
        for c in report.checks
        if c.id.startswith(CONFIG_ID) and c.status is not Status.PASS
    ]
    assert not problems, problems


# ------------------------------------------------------------------------------------------------ the conf parser
def test_the_parser_handles_comments_blocks_templates_and_appended_sections():
    text = (
        "; comment\n[a](!)\nx = 1 ; trailing\n;-- block\nx = 99\n--;\ny = 2\n[b](a)\nz = 3\n[a](+)\nw = a\\;b\n[c]\n"
        "exten => 6000,1,NoOp()\n same => n,Hangup()\n#include other.conf\n"
    )
    sections = conf.parse_conf(text)
    assert [s.name for s in sections] == ["a", "b", "c"]
    assert [(i.key, i.value) for i in sections[0].items] == [("x", "1"), ("y", "2"), ("w", "a;b")]
    templates = {s.name: s for s in sections}
    assert [(i.key, i.value) for i in conf.effective_items(sections[1], templates)] == [
        ("x", "1"),
        ("y", "2"),
        ("w", "a;b"),
        ("z", "3"),
    ]
    assert [(s.extension, s.text) for s in conf.dialplan_steps(sections)] == [("6000", "NoOp()"), ("6000", "Hangup()")]


def test_an_inheritance_loop_and_a_very_long_line_do_not_hang_the_parser():
    long_lines = "k" * 100_000 + "\n" + "k " * 50_000 + "\n" + " " * 100_000
    sections = conf.parse_conf("[a](b)\nx = 1\n[b](a)\ny = 2\n" + long_lines)
    templates = {s.name: s for s in sections}
    assert [i.key for i in conf.effective_items(sections[0], templates)] == ["y", "x"]


def test_two_sections_may_share_a_name_when_they_are_different_objects():
    findings, judged = conf.pjsip_findings(
        conf.ConfigFiles(
            True,
            {
                "pjsip": conf.ConfigFile(
                    "pjsip.conf.template",
                    tuple(
                        conf.parse_conf(
                            "[tmpl](!)\ntype = endpoint\nauth = a\ndisallow = all\nallow = ulaw,alaw\nidentify_by = username\n"
                            "allow_transfer = no\nallow_unauthenticated_options = no\n[6001](tmpl)\n[6001]\ntype = aor\n"
                        )
                    ),
                )
            },
        )
    )
    assert judged == 1 and findings == []  # the aor named 6001 is not mistaken for the endpoint named 6001


def test_the_directory_is_found_from_a_source_checkout_and_not_when_it_is_named_but_absent(tmp_path, monkeypatch):
    checkout = tmp_path / "repo" / "infrastructure" / "asterisk"
    checkout.mkdir(parents=True)
    (tmp_path / "repo" / "services" / "api").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "repo" / "services" / "api")  # the doctor is usually run from services/api
    assert REAL_FIND_DIRECTORY() == checkout
    assert REAL_FIND_DIRECTORY(checkout) == checkout
    assert REAL_FIND_DIRECTORY(tmp_path / "nowhere") is None  # a directory that was named is never replaced by another


# ------------------------------------------------------------------------------------------------------- redaction
def test_numbers_are_kept_only_for_a_check_that_asks_and_secrets_are_still_redacted():
    text = "UDP 5060 on 192.168.100.200, extension 6000, 1800 s, password=123456 and Bearer abc.def"
    plain = _plain(text)
    assert "[digits]" in plain and "5060" not in plain  # the default is unchanged: this is why the flag exists
    kept = _plain(text, keep_numbers=True)
    assert "UDP 5060 on 192.168.100.200, extension 6000, 1800 s" in kept
    assert "123456" not in kept and "password=[redacted]" in kept and "abc.def" not in kept
    assert _plain("a\ue000b 5060", keep_numbers=True) == _plain(
        "a\ue000b 5060"
    )  # text that could clash: redacted as before
    check = Check("x", "g", "t", Status.PASS, text, text, keep_numbers=True).safe()
    assert "5060" in check.detail and "5060" in check.fix and check.keep_numbers
    assert "5060" not in Check("x", "g", "t", Status.PASS, text).safe().detail


def assert_reaches_the_terminal_as_written(checks: list[Check]) -> None:
    """The hand-written sentences must not be altered by the redaction (a key=value, an address or a long number would)."""
    assert checks
    for check in checks:
        safe = check.safe()
        assert (safe.detail, safe.fix) == (check.detail, check.fix), check.id


def test_every_fixed_sentence_of_the_asterisk_group_survives_the_redaction():
    bad = memory_files(
        extensions_conf=DIALPLAN
        + "exten => _X.,1,Dial(PJSIP/trunk/${EXTEN})\n same => n,Set(CURLOPT(userpwd)=asterisk:literal)\n",
        pjsip_conf_template=mutate(PJSIP, "@@SIP_PASSWORD_6001@@", "literal") + "\n[trunk]\ntype = registration\n",
        modules_conf=MODULES + "load = res_ari.so\n",
        http_conf="[general]\nenabled = yes\n",
        asterisk_conf="[options]\nverbose = 5\n",
    )
    wrong = settings_for(
        asterisk_webhook_secret=None,
        asterisk_media_peers=["10.0.0.0/8", "bad entry!"],
        asterisk_media_bind="0.0.0.0",
        stt_provider="simulator",
        max_active_calls=11,
        max_call_duration_s=1801,
    )
    for settings, files in (
        (settings_for(), memory_files()),
        (settings_for(), bad),
        (wrong, bad),
        (settings_for(), conf.ConfigFiles(False, {})),
        (settings_for(telephony_provider="azure", asterisk_extension="7000"), memory_files()),
    ):
        assert_reaches_the_terminal_as_written(ast.asterisk_offline(settings, files))
    assert_reaches_the_terminal_as_written(unverified_checks(settings_for(), azure=True, twilio=True, asterisk=True))
    assert_reaches_the_terminal_as_written([probes.rtp_check((10000, 10019)), probes.rtp_check(None)])


# ------------------------------------------------------------------------------------------- what cannot be proven
def test_the_unprovable_items_name_each_provider_that_is_checked_and_keep_the_old_wording():
    settings = settings_for()
    azure = {c.id: c for c in unverified_checks(settings, azure=True, twilio=False)}
    assert azure["live.barge_in"].detail == (
        "the StopAudio frame and the pacing of outbound audio were only exercised against a fake media socket."
    )
    assert "live.sip_call" not in azure and "live.pstn_inbound" in azure
    twilio = {c.id: c for c in unverified_checks(settings, azure=False, twilio=True)}
    assert twilio["live.barge_in"].detail.startswith("the clear message was only exercised")
    sip = {c.id: c for c in unverified_checks(settings, azure=False, twilio=False, asterisk=True)}
    assert set(sip) == {"live.sip_call", "live.barge_in", "live.recognition_quality", "live.takeover", "legal.review"}
    assert (
        "scripted AudioSocket client" in sip["live.barge_in"].detail and "SIP extension" in sip["live.takeover"].detail
    )
    assert "Kannada recognition by the local model is experimental" in sip["live.recognition_quality"].detail
    azure_speech = {
        c.id: c for c in unverified_checks(settings_for(stt_provider="azure"), azure=False, twilio=False, asterisk=True)
    }
    assert "local model" not in azure_speech["live.recognition_quality"].detail
    everyone = unverified_checks(settings, azure=True, twilio=True, asterisk=True)
    assert len({c.id for c in everyone}) == len(everyone)  # shared items appear once
    mixed = {c.id: c for c in everyone}
    assert "fake media socket" in mixed["live.barge_in"].detail and "For Asterisk," in mixed["live.barge_in"].detail
    assert "live.pstn_inbound" in mixed and "live.sip_call" in mixed


async def test_provider_all_includes_asterisk_and_asterisk_alone_is_not_the_simulator_warning():
    assert normalise_providers(["all"])[2] == "asterisk"
    everything_report = await run_doctor(Settings(_env_file=None), providers=("all",))
    ids = by_id(everything_report)
    assert "asterisk.callback_secret" in ids and "acs.connection_string" in ids
    unprovable = [check.id for check in everything_report.checks if check.group == "Not provable from here"]
    assert len(unprovable) == len(set(unprovable))  # shared items appear once
    assert {"live.pstn_inbound", "live.sip_call", "legal.review"} <= set(unprovable)
    simulator = await run_doctor(Settings(_env_file=None), providers=("simulator",))
    assert "--provider asterisk" in by_id(simulator)["doctor.scope"].fix
    assert "doctor.scope" not in by_id(await doctor())


# ------------------------------------------------------------------------------------------------- SIP OPTIONS probe
class UdpServer:
    """A throwaway UDP socket that answers (or not) like a SIP service would."""

    def __init__(self, reply: Callable[[bytes], bytes | None]) -> None:
        self.received: list[bytes] = []
        self._reply = reply
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(0.1)
        self.port: int = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, address = self._sock.recvfrom(65535)
            except (TimeoutError, ConnectionError):
                continue
            except OSError:
                return
            self.received.append(data)
            answer = self._reply(data)
            if answer is not None:
                self._sock.sendto(answer, address)

    def __enter__(self) -> "UdpServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(2)
        self._sock.close()


def sip_answer(status: str, server: str = "Sparta-Asterisk") -> Callable[[bytes], bytes]:
    def build(request: bytes) -> bytes:
        headers = {}
        for line in request.decode("ascii").split("\r\n")[1:]:
            name, _, value = line.partition(":")
            headers[name.lower()] = value.strip()
        return (
            f"SIP/2.0 {status}\r\nVia: {headers['via']}\r\nFrom: {headers['from']}\r\nTo: {headers['to']};tag=abc\r\n"
            f"Call-ID: {headers['call-id']}\r\nCSeq: {headers['cseq']}\r\nServer: {server}\r\nContent-Length: 0\r\n\r\n"
        ).encode("ascii")

    return build


async def sip_check(port: int, timeout_s: float = 2.0, host: str = "127.0.0.1") -> Check:
    return await probes.sip_check(settings_for(asterisk_sip_host=host, asterisk_sip_port=port), timeout_s)


@pytest.mark.parametrize(
    ("status", "wants"),
    [("401 Unauthorized", True), ("403 Forbidden", True), ("200 OK", False), ("404 Not Found", False)],
)
async def test_any_sip_status_line_means_the_service_answered(status, wants):
    with UdpServer(sip_answer(status)) as server:
        check = await sip_check(server.port)
    assert check.status is Status.PASS and f"status {status[:3]}" in check.detail, check.detail
    assert ("wants credentials" in check.detail) is wants
    assert "Sparta-Asterisk" in check.detail  # the Server header, shown as plain short text
    assert str(server.port) in check.detail and "[digits]" not in check.safe().detail


async def test_the_probe_sends_exactly_one_credential_free_options_with_fresh_ids():
    with UdpServer(sip_answer("401 Unauthorized")) as server:
        await sip_check(server.port)
        await sip_check(server.port)
    assert len(server.received) == 2  # one datagram per probe: no retransmission, no second request
    first, second = (data.decode("ascii") for data in server.received)
    assert first.startswith("OPTIONS sip:127.0.0.1 SIP/2.0\r\n") and first.endswith("\r\n\r\n")
    for request in (first, second):
        lowered = request.lower()
        assert "authorization" not in lowered and "password" not in lowered and "content-length: 0" in lowered
        assert "branch=z9hg4bk" in lowered and "cseq: 1 options" in lowered
    ids = [next(line for line in req.split("\r\n") if line.startswith("Call-ID")) for req in (first, second)]
    branches = [req.split("branch=")[1].split(";")[0] for req in (first, second)]
    assert ids[0] != ids[1] and branches[0] != branches[1]  # random every time


@pytest.mark.parametrize(
    "answer",
    [
        b"hello this is not sip",
        b"OPTIONS sip:x SIP/2.0\r\n\r\n",
        b"SIP/2.0 99 Too Low\r\n\r\n",
        b"SIP/2.0 700 Too High\r\n\r\n",
        b"\x00\xff" * 40,
    ],
)
async def test_a_reply_that_is_not_a_sip_response_is_blocked(answer):
    with UdpServer(lambda request: answer) as server:
        check = await sip_check(server.port)
    assert check.status is Status.BLOCKED and "not a SIP response" in check.detail, check.detail


async def test_a_sip_service_that_never_answers_is_blocked_with_what_to_check():
    with UdpServer(lambda request: None) as server:
        check = await sip_check(server.port, timeout_s=0.3)
        assert len(server.received) == 1  # it did get exactly one request, and one only
    assert check.status is Status.BLOCKED and "no SIP answer" in check.detail
    for hint in ("container", "published", "firewall", "UDP"):
        assert hint in check.fix, hint


async def test_a_closed_udp_port_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    check = await sip_check(port, timeout_s=1.0)
    assert check.status is Status.BLOCKED  # "refused" where the OS reports ICMP port unreachable, "no answer" otherwise


async def test_an_unresolvable_or_invalid_sip_host_is_blocked_without_echoing_it():
    check = await sip_check(5060, host="no-such-host.invalid")
    assert check.status is Status.BLOCKED and "no-such-host" not in check.safe().detail
    bad = await sip_check(5060, host="evil\r\nhost")
    assert bad.status is Status.BLOCKED and "not a host name or address" in bad.detail and "evil" not in bad.detail


def test_the_options_request_brackets_an_ipv6_literal_and_is_ascii():
    request = probes.options_request("::1", ("::1", 5061)).decode("ascii")
    assert request.startswith("OPTIONS sip:[::1] SIP/2.0\r\n") and "SIP/2.0/UDP [::1]:5061" in request


# --------------------------------------------------------------------------------------------- media listener probe
async def media_check(port: int, bind: str = "127.0.0.1", timeout_s: float = 3.0) -> Check:
    return await probes.media_check(settings_for(asterisk_media_bind=bind, asterisk_media_port=port), timeout_s)


@contextlib.asynccontextmanager
async def tcp_listener(*, drop: bool = False) -> AsyncIterator[tuple[int, list[bytes]]]:
    """A listener that records what a client sends. ``drop`` closes at once, like the peer allow-list does."""
    seen: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not drop:
            with contextlib.suppress(TimeoutError, ConnectionError):
                seen.append(await asyncio.wait_for(reader.read(100), 1.0))
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1], seen
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(("drop", "bind"), [(False, "127.0.0.1"), (True, "127.0.0.1"), (False, "0.0.0.0")])
async def test_a_tcp_connection_is_made_and_closed_without_sending_anything(drop, bind):
    async with tcp_listener(drop=drop) as (port, seen):
        check = await media_check(port, bind)
        await asyncio.sleep(0.2)
    assert check.status is Status.PASS and f"127.0.0.1:{port}" in check.safe().detail, check.detail
    assert seen == ([] if drop else [b""])  # end of stream, not a byte: nothing that could pass for a handshake
    assert "media connection refused" in check.detail  # tells the owner about the one warning the probe causes


async def test_a_closed_media_port_means_the_api_is_not_running_which_is_unverified_not_blocked():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    check = await media_check(port, timeout_s=4.0)
    assert check.status is Status.UNVERIFIED and "nothing listens yet" in check.detail, check.detail
    assert "SPARTA_TELEPHONY_PROVIDER=asterisk" in check.fix


async def test_media_port_zero_has_nothing_to_probe():
    check = await media_check(0)
    assert check.status is Status.UNVERIFIED and "random port" in check.detail


def test_a_listener_on_every_address_is_probed_on_loopback():
    assert probes.probe_host("0.0.0.0") == "127.0.0.1" and probes.probe_host("::") == "::1"
    assert probes.probe_host("192.168.1.20") == "192.168.1.20" and probes.probe_host("localhost") == "localhost"


def test_the_rtp_ports_are_never_claimed_to_be_proven():
    check = probes.rtp_check((10000, 10019)).safe()
    assert check.status is Status.UNVERIFIED and "UDP ports 10000 to 10019" in check.detail
    assert "ANDROID_SIP_TESTING" in check.fix
    assert probes.rtp_check(None).status is Status.UNVERIFIED


# ----------------------------------------------------------------------------------------------- online, together
async def test_online_adds_the_sip_media_and_rtp_checks_and_the_stores_but_makes_no_http_request(tmp_path, sqlite_url):
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    with UdpServer(sip_answer("401 Unauthorized")) as sip:
        async with (
            tcp_listener() as (media_port, _),
            httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http,
        ):
            settings = settings_for(
                database_url=sqlite_url, redis_url=None, asterisk_sip_port=sip.port, asterisk_media_port=media_port
            )
            report = await doctor(settings, write_config(tmp_path), online=True, http=http, timeout_s=2.0)
    checks = by_id(report)
    assert checks["asterisk.sip_options"].status is Status.PASS
    assert checks["asterisk.media_listener"].status is Status.PASS
    assert checks["asterisk.rtp_ports"].status is Status.UNVERIFIED
    assert "10000 to 10019" in checks["asterisk.rtp_ports"].detail
    assert (
        checks["db.connect"].status is Status.PASS and checks["db.schema"].status is Status.PASS
    )  # the CORE checks, reused
    assert not any(ident.startswith(("callback.", "speech.", "twilio")) for ident in checks)
    assert report.online and not report.blocked
    assert SECRET not in everything(report)


async def test_online_reports_an_unreachable_sip_service_as_blocked_and_the_exit_code_follows(tmp_path, sqlite_url):
    with UdpServer(lambda request: None) as sip:
        settings = settings_for(
            database_url=sqlite_url, redis_url=None, asterisk_sip_port=sip.port, asterisk_media_port=0
        )
        report = await doctor(settings, write_config(tmp_path), online=True, timeout_s=0.3)
    assert by_id(report)["asterisk.sip_options"].status is Status.BLOCKED and report.exit_code() == 1


async def test_an_offline_run_never_calls_a_probe(tmp_path, monkeypatch):
    async def forbidden(*args: object, **kwargs: object) -> list[Check]:
        raise AssertionError("an offline run must not probe anything")

    monkeypatch.setattr(probes, "asterisk_online", forbidden)
    report = await doctor(directory=write_config(tmp_path))
    assert not report.online
    assert not {"asterisk.sip_options", "asterisk.media_listener", "asterisk.rtp_ports"} & by_id(report).keys()


async def test_billable_probes_run_for_asterisk_only_when_azure_services_are_selected(
    tmp_path, sqlite_url, monkeypatch
):
    calls: list[str] = []

    async def fake_billable(settings: Settings, *, http: httpx.AsyncClient, timeout_s: float) -> list[Check]:
        calls.append("billable")
        return []

    monkeypatch.setattr("sparta.doctor.billable.run_billable", fake_billable)
    for changes, expected in (({}, 0), ({"stt_provider": "azure"}, 1)):
        calls.clear()
        settings = settings_for(database_url=sqlite_url, redis_url=None, asterisk_media_port=0, **changes)
        await doctor(settings, write_config(tmp_path), online=True, allow_billable=True, timeout_s=0.3)
        assert len(calls) == expected, changes


# ------------------------------------------------------------------------------------------------------------- CLI
def cli_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str) -> None:
    values = {
        "SPARTA_ENV": "test",
        "SPARTA_TELEPHONY_PROVIDER": "asterisk",
        "SPARTA_STT_PROVIDER": "local",
        "SPARTA_TTS_PROVIDER": "local",
        "SPARTA_ASTERISK_WEBHOOK_SECRET": SECRET,
        **extra,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)  # no .env to pick up


def test_the_command_checks_asterisk_prints_no_secret_and_exits_zero_when_nothing_is_blocked(
    monkeypatch, tmp_path, capsys
):
    cli_environment(monkeypatch, tmp_path)
    directory = write_config(tmp_path)
    monkeypatch.setattr(conf, "find_directory", lambda explicit=None: directory)
    assert cli.main(["doctor", "--provider", "asterisk"]) == 0
    out = capsys.readouterr().out
    assert "Asterisk (local SIP telephony)" in out and "Verdict: NO BLOCKERS FOUND" in out and SECRET not in out
    assert cli.main(["doctor", "--provider", "asterisk", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["providers"] == ["asterisk"] and payload["summary"]["BLOCKED"] == 0


def test_the_command_exits_non_zero_when_the_secret_is_missing_and_still_says_what_to_do(monkeypatch, tmp_path, capsys):
    cli_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("SPARTA_ASTERISK_WEBHOOK_SECRET")
    assert cli.main(["doctor", "--provider", "asterisk", "--json"]) == 1
    checks = {c["id"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["asterisk.callback_secret"]["status"] == "BLOCKED"
    assert "secrets.token_urlsafe(32)" in checks["asterisk.callback_secret"]["fix"]


def test_provider_asterisk_is_a_choice_and_the_help_says_what_it_uses(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--help"])
    assert caught.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "{azure,twilio,asterisk,simulator,all}" in help_text
    assert "SPARTA_STT_PROVIDER" in help_text and "SIP OPTIONS" in help_text
    with pytest.raises(SystemExit) as invalid:
        cli.main(["doctor", "--provider", "plivo"])
    assert invalid.value.code == 2
