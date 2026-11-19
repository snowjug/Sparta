"""Offline checks of ``sparta doctor --provider asterisk``: free local SIP through Asterisk, with no phone network.

What Sparta can see without a phone: its own settings (the callback secret, who may open the media connection, the limits,
which speech providers are selected) and the Asterisk configuration kept in ``infrastructure/asterisk/``. What it cannot see
is a real SIP client being heard, so those items are listed as UNVERIFIED by :mod:`sparta.doctor.runner` with the steps
that prove them. Every text here is written by hand without a value: the callback secret is only ever "present", "absent"
or "too short", and file findings carry a file name and a line number, never the line.
"""

import importlib
import importlib.metadata
import ipaddress
import re
from collections.abc import Callable, Sequence

from sparta.config import MIN_ASTERISK_SECRET_CHARS, Settings, _peer_problem
from sparta.doctor import asterisk_conf as conf
from sparta.doctor.asterisk_conf import ConfigFiles, Finding
from sparta.doctor.checks import ASTERISK, media_format_check, openai_checks, speech_checks, speech_sdk_check
from sparta.doctor.model import Check, Status

_RANK = {Status.BLOCKED: 0, Status.WARNING: 1, Status.UNVERIFIED: 2, Status.PASS: 3}
_SECRET_CHARS = re.compile(r"[A-Za-z0-9._~-]+")  # what the bundled Asterisk container accepts as the callback secret
_EXTENSION = re.compile(r"[0-9]{2,8}")
_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
LOCAL_EXTRA = "pip install 'sparta-api[local-speech]'"
MODELS_FETCH = "python -m sparta models fetch"
MAX_LISTED = 5


def _check(id_: str, title: str, status: Status, detail: str = "", fix: str = "") -> Check:
    return Check(id_, ASTERISK, title, status, detail, fix, keep_numbers=True)


def _worst(statuses: Sequence[Status]) -> Status:
    return min(statuses, key=_RANK.__getitem__)


def plain_host(value: str) -> str:
    """A host as written in the settings if it is plainly a host or an address, else a neutral phrase (never odd text)."""
    return value.strip() if re.fullmatch(r"[A-Za-z0-9.:\-\[\]]{1,64}", value.strip()) else "the configured address"


# ----------------------------------------------------------------------------------------------------- settings
def provider_check(settings: Settings) -> Check:
    title = "Telephony provider selected"
    if settings.telephony_provider == "asterisk":
        return _check(
            "asterisk.provider",
            title,
            Status.PASS,
            "SPARTA_TELEPHONY_PROVIDER=asterisk: the API opens the media listener and answers the dialplan's callbacks.",
        )
    return _check(
        "asterisk.provider",
        title,
        Status.WARNING,
        f"SPARTA_TELEPHONY_PROVIDER is {settings.telephony_provider!r}, so the API would not take Asterisk calls. "
        "The checks below ran anyway, so you can prepare the rest.",
        "Set SPARTA_TELEPHONY_PROVIDER=asterisk.",
    )


def secret_check(settings: Settings) -> Check:
    """The dialplan authenticates its callbacks with this secret. Only whether it is usable is said, never what it is."""
    title = "Dialplan callback secret"
    generate = (
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))" and set '
        "SPARTA_ASTERISK_WEBHOOK_SECRET to it (or SPARTA_ASTERISK_WEBHOOK_SECRET_FILE to a file whose first line is it)."
    )
    secret = settings.asterisk_secret()
    if secret is None:
        if settings.asterisk_webhook_secret is None and settings.asterisk_webhook_secret_file:
            detail = (
                "SPARTA_ASTERISK_WEBHOOK_SECRET_FILE is set, but the file cannot be read or its first line is empty."
            )
        elif settings.asterisk_webhook_secret is not None:
            detail = "SPARTA_ASTERISK_WEBHOOK_SECRET is set but empty."
        else:
            detail = (
                "absent: neither SPARTA_ASTERISK_WEBHOOK_SECRET nor SPARTA_ASTERISK_WEBHOOK_SECRET_FILE is set, so "
                "every dialplan callback would be refused."
            )
        return _check("asterisk.callback_secret", title, Status.BLOCKED, detail, generate)
    if len(secret) < MIN_ASTERISK_SECRET_CHARS:
        return _check(
            "asterisk.callback_secret",
            title,
            Status.BLOCKED,
            f"too short: at least {MIN_ASTERISK_SECRET_CHARS} characters are required.",
            generate,
        )
    if not _SECRET_CHARS.fullmatch(secret):
        return _check(
            "asterisk.callback_secret",
            title,
            Status.WARNING,
            f"present and at least {MIN_ASTERISK_SECRET_CHARS} characters, but it contains characters outside letters, "
            "digits and . _ ~ - : the bundled Asterisk container refuses to start with such a value.",
            generate,
        )
    return _check(
        "asterisk.callback_secret",
        title,
        Status.PASS,
        f"present, at least {MIN_ASTERISK_SECRET_CHARS} characters (the value is not shown, and is not checked against "
        "the one Asterisk holds: only a live call proves that).",
    )


def _bind_kind(bind: str) -> str:
    value = bind.strip().strip("[]")
    if value.lower() == "localhost":
        return "loopback"
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "other"
    if address.is_unspecified:
        return "wildcard"
    return "loopback" if address.is_loopback else "other"


def peers_check(settings: Settings) -> Check:
    title = "Media peers (who may open the AudioSocket connection)"
    entries = list(settings.asterisk_media_peers)
    fix = (
        "List only Asterisk: its address or host name (asterisk in Docker Compose) in SPARTA_ASTERISK_MEDIA_PEERS, "
        "and bind SPARTA_ASTERISK_MEDIA_BIND to loopback unless Asterisk runs elsewhere."
    )
    if not entries:
        return _check(
            "asterisk.media_peers",
            title,
            Status.BLOCKED,
            "no peer is allowed, so every media connection from Asterisk would be dropped.",
            fix,
        )
    problems = []
    for index, entry in enumerate(entries, start=1):
        why = _peer_problem(entry)
        if why:
            message = why.replace(f"'{entry}'", "it", 1)
            problems.append(
                f"entry {index}: " + ("it is not an acceptable peer" if f"'{entry}'" in message else message)
            )
    if problems:
        return _check("asterisk.media_peers", title, Status.BLOCKED, "; ".join(problems) + ".", fix)
    networks: list[tuple[int, ipaddress.IPv4Network | ipaddress.IPv6Network]] = []
    hosts: list[str] = []
    for index, entry in enumerate(entries, start=1):
        try:
            networks.append((index, ipaddress.ip_network(entry, strict=False)))
        except ValueError:
            hosts.append(entry.lower())
    bind = settings.asterisk_media_bind
    kind = _bind_kind(bind)
    where = f"{plain_host(bind)}:{settings.asterisk_media_port}"
    warnings: list[str] = []
    only_loopback = all(network.is_loopback for _, network in networks) and all(h == "localhost" for h in hosts)
    if only_loopback and kind != "loopback":
        warnings.append(
            f"only loopback peers are allowed, but the listener binds {where}: Asterisk in a container connects from "
            "another address and would be dropped"
        )
    if kind != "loopback":
        warnings.extend(
            f"entry {index} is a very wide range (/{network.prefixlen}) for a listener that is not loopback-only"
            for index, network in networks
            if network.prefixlen < (16 if network.version == 4 else 48)
        )
    if warnings:
        return _check("asterisk.media_peers", title, Status.WARNING, "; ".join(warnings) + ".", fix)
    return _check(
        "asterisk.media_peers",
        title,
        Status.PASS,
        f"{len(entries)} peer(s) allowed ({len(networks)} address or range entries, {len(hosts)} host names), none of "
        f"them everything. The listener binds {where}; a connection from anywhere else is dropped before a byte is read.",
    )


def extensions_check(settings: Settings) -> Check:
    title = "Extensions"
    sparta, owner = settings.asterisk_extension, settings.asterisk_owner_extension
    problems = [
        f"{name} must be plain digits (2 to 8)"
        for name, value in (("SPARTA_ASTERISK_EXTENSION", sparta), ("SPARTA_ASTERISK_OWNER_EXTENSION", owner))
        if not _EXTENSION.fullmatch(value)
    ]
    if sparta == owner:
        problems.append("SPARTA_ASTERISK_EXTENSION and SPARTA_ASTERISK_OWNER_EXTENSION must differ")
    if problems:
        return _check(
            "asterisk.extensions",
            title,
            Status.BLOCKED,
            "; ".join(problems) + ".",
            "Use two different numbers, for example 6000 for Sparta and 6002 for the owner's SIP phone.",
        )
    return _check(
        "asterisk.extensions",
        title,
        Status.PASS,
        f"Sparta answers extension {sparta}; Take Over rings extension {owner}, a SIP phone registered on this server "
        "(never a phone number).",
    )


def limits_check(settings: Settings) -> Check:
    title = "Call limits"
    calls, seconds, minutes = settings.max_active_calls, settings.max_call_duration_s, settings.daily_call_minutes_cap
    connections = settings.asterisk_max_media_connections
    problems: list[str] = []
    if calls < 1:
        problems.append("SPARTA_MAX_ACTIVE_CALLS is below 1, so every call would be refused as busy")
    elif calls > 10:
        problems.append(
            "SPARTA_MAX_ACTIVE_CALLS is above 10: every live call runs recognition and synthesis on this machine"
        )
    if seconds > 1800:
        problems.append(
            "SPARTA_MAX_CALL_DURATION_S is above 1800 seconds (30 minutes): a screening call needs a minute or two"
        )
    if calls > connections:
        problems.append(
            f"SPARTA_MAX_ACTIVE_CALLS ({calls}) is above SPARTA_ASTERISK_MAX_MEDIA_CONNECTIONS ({connections}): the "
            "media connection of a call beyond that would be refused"
        )
    numbers = (
        f"at most {calls} call(s) at once, {seconds} s per call, "
        + (f"{minutes:g} call-minutes" if minutes > 0 else "no minute limit")
        + f" per owner per UTC day; the media listener takes up to {connections} connections."
    )
    if problems:
        return _check(
            "asterisk.limits",
            title,
            Status.WARNING,
            "; ".join(problems) + ". Now: " + numbers,
            "Keep 1 to 10 calls at once and calls of at most 30 minutes, and keep the media connection limit at or "
            "above the number of calls.",
        )
    return _check("asterisk.limits", title, Status.PASS, numbers)


# ------------------------------------------------------------------------------------------------------ speech
def speech_selection_check(settings: Settings) -> Check:
    title = "Speech providers for a live call"
    problems: list[str] = []
    for what, value, reasons in (
        (
            "speech recognition (SPARTA_STT_PROVIDER)",
            settings.stt_provider,
            {"simulator": "the simulator, which recognises nothing", "fake": "'fake', which is test-only"},
        ),
        (
            "speech synthesis (SPARTA_TTS_PROVIDER)",
            settings.tts_provider,
            {
                "simulator": "the simulator, which speaks nothing",
                "fake": "'fake', which is test-only (tones, not speech)",
            },
        ),
    ):
        if value in reasons:
            problems.append(f"{what} is {reasons[value]}")
    if problems:
        return _check(
            "asterisk.speech",
            title,
            Status.BLOCKED,
            "; ".join(problems) + ". A live call would be deaf or silent.",
            "Set SPARTA_STT_PROVIDER=local and SPARTA_TTS_PROVIDER=local (free: needs the local-speech extra and the "
            "downloaded models), or azure for either.",
        )
    return _check(
        "asterisk.speech",
        title,
        Status.PASS,
        f"speech recognition: {settings.stt_provider}; speech synthesis: {settings.tts_provider}.",
    )


def _package_check(id_: str, title: str, module: str, distribution: str) -> Check:
    """Whether the engine imports here. Nothing is loaded into memory and no model is touched."""
    try:
        importlib.import_module(module)
    except ImportError:
        return _check(
            id_,
            title,
            Status.UNVERIFIED,
            f"{distribution} is not installed in this environment.",
            f"Install the local-speech extra: {LOCAL_EXTRA} (in the environment the API runs in).",
        )
    except Exception as exc:  # a broken native library can fail in more ways than ImportError
        return _check(
            id_,
            title,
            Status.UNVERIFIED,
            f"{distribution} is installed, but importing it raised {type(exc).__name__}.",
            f"Reinstall the local-speech extra: {LOCAL_EXTRA}.",
        )
    try:
        version = f" {importlib.metadata.version(distribution)}"
    except importlib.metadata.PackageNotFoundError:
        version = ""
    return _check(id_, title, Status.PASS, f"{distribution}{version} imports (no model is loaded by this check).")


def local_package_checks(settings: Settings) -> list[Check]:
    out: list[Check] = []
    if settings.stt_provider == "local":
        out.append(
            _package_check(
                "asterisk.local_stt", "Local speech recognition (faster-whisper)", "faster_whisper", "faster-whisper"
            )
        )
    if settings.tts_provider == "local":
        out.append(_package_check("asterisk.local_tts", "Local speech synthesis (Piper)", "piper", "piper-tts"))
    return out


def _model_entries(result: object) -> list[tuple[str, str, bool, bool | None, str | None]] | None:
    """``(kind, name, installed, verified, locale)`` of the entries the settings select; None if the result is unfamiliar."""
    if not isinstance(result, list | tuple):
        return None
    selected: list[tuple[str, str, bool, bool | None, str | None]] = []
    marked = False
    for entry in result:
        kind = getattr(entry, "kind", None)
        name = getattr(entry, "name", None)
        installed = getattr(entry, "installed", None)
        if kind not in ("stt", "tts") or not isinstance(name, str) or not isinstance(installed, bool):
            return None
        verified = getattr(entry, "verified", None)
        locale = getattr(entry, "locale", None)
        if getattr(entry, "selected", False) is True:
            marked = True
            selected.append(
                (
                    kind,
                    name if _PLAIN_NAME.fullmatch(name) else "a custom entry",
                    installed,
                    verified if isinstance(verified, bool) else None,
                    locale if isinstance(locale, str) and _PLAIN_NAME.fullmatch(locale) else None,
                )
            )
    return selected if marked else None


def _model_status_of(settings: Settings, model_status: Callable[..., object]) -> object:
    try:
        return model_status(settings, verify=True)  # hash what is installed: "verified" means the SHA-256 matches
    except TypeError:
        return model_status(settings)


def local_models_check(settings: Settings) -> Check | None:
    """The configured faster-whisper model and Piper voices: installed, and matching their pinned SHA-256."""
    local = {"stt": settings.stt_provider == "local", "tts": settings.tts_provider == "local"}
    if not any(local.values()):
        return None
    title = "Local speech models installed and verified"
    by_hand = f"Check by hand with `python -m sparta models list`, and install what is missing with `{MODELS_FETCH}`."
    try:
        module = importlib.import_module("sparta.providers.local_models")
        model_status = module.model_status
    except (ImportError, AttributeError):
        return _check(
            "asterisk.local_models",
            title,
            Status.UNVERIFIED,
            "local model check not available: the model manifest module could not be used here.",
            by_hand,
        )
    try:
        result = _model_status_of(settings, model_status)
    except Exception as exc:  # an unreadable model directory must not crash the report
        return _check(
            "asterisk.local_models",
            title,
            Status.UNVERIFIED,
            f"the model check raised {type(exc).__name__}.",
            by_hand,
        )
    entries = _model_entries(result)
    if entries is None:
        return _check(
            "asterisk.local_models",
            title,
            Status.UNVERIFIED,
            "local model check not available: its result was not in the expected form.",
            by_hand,
        )
    lines: list[str] = []
    statuses: list[Status] = []
    for kind, label in (("stt", "speech recognition"), ("tts", "speech synthesis")):
        if not local[kind]:
            continue
        chosen = [entry for entry in entries if entry[0] == kind]
        if not chosen:
            lines.append(f"{label}: no model or voice is selected")
            statuses.append(Status.BLOCKED)
            continue
        missing = 0
        for _, name, installed, verified, locale in chosen:
            subject = f"{label} model {name}" if kind == "stt" else f"voice {name}" + (f" ({locale})" if locale else "")
            if not installed:
                missing += 1
                lines.append(f"{subject}: not installed or incomplete")
            elif verified is False:
                lines.append(f"{subject}: CORRUPT, the SHA-256 does not match the pinned value")
                statuses.append(Status.BLOCKED)
            elif verified is None:
                lines.append(f"{subject}: installed, but not hash-checked (not in the manifest)")
                statuses.append(Status.UNVERIFIED)
            else:
                lines.append(f"{subject}: installed, SHA-256 verified")
        if missing:
            # without a recognition model no call can be understood; a locale without a voice is refused, the rest speak
            statuses.append(Status.BLOCKED if kind == "stt" or missing == len(chosen) else Status.WARNING)
    status = _worst(statuses) if statuses else Status.PASS
    fix = ""
    if status is not Status.PASS:
        fix = f"Run `{MODELS_FETCH}` to download and verify them (`python -m sparta models list` shows what is installed)."
    return _check("asterisk.local_models", title, status, "; ".join(lines) + ".", fix)


def speech_checks_for(settings: Settings) -> list[Check]:
    """Everything about speech for a live Asterisk call: the selection, Azure's checks if used, local packages and models."""
    out = [speech_selection_check(settings)]
    if "azure" in (settings.stt_provider, settings.tts_provider):
        out.extend(speech_checks(settings))
        out.append(speech_sdk_check(settings))
    out.extend(local_package_checks(settings))
    models = local_models_check(settings)
    if models is not None:
        out.append(models)
    return out


# ------------------------------------------------------------------------------------------- configuration files
def _verdict(id_: str, title: str, findings: Sequence[Finding], ok: str) -> Check:
    if not findings:
        return _check(id_, title, Status.PASS, ok)
    shown = [f"{f.where}: {f.what}" for f in findings[:MAX_LISTED]]
    if len(findings) > MAX_LISTED:
        shown.append(f"and {len(findings) - MAX_LISTED} more")
    fixes = " ".join(dict.fromkeys(f.fix for f in findings if f.fix))
    return _check(id_, title, _worst([f.severity for f in findings]), "; ".join(shown) + ".", fixes)


def _unverified(id_: str, title: str, why: str) -> Check:
    return _check(
        id_,
        title,
        Status.UNVERIFIED,
        why,
        "Run the doctor from a source checkout so that infrastructure/asterisk/ can be read, or check that file by hand.",
    )


def files_check(files: ConfigFiles) -> Check:
    title = "Asterisk configuration files in the repository"
    if not files.directory:
        return _check(
            "asterisk.config.files",
            title,
            Status.UNVERIFIED,
            "infrastructure/asterisk/ was not found from the current directory or from this installation, so the "
            "configuration could not be read.",
            "Run `sparta doctor` from a source checkout of Sparta (the repository root or services/api): a packaged "
            "install does not contain the Asterisk configuration.",
        )
    missing = [
        conf.FILES[logical][0]
        for logical in conf.REQUIRED
        if logical not in files.files and not set(conf.FILES[logical]) & set(files.unreadable)
    ]
    if missing or files.unreadable:
        parts = []
        if missing:
            parts.append("not found: " + ", ".join(missing))
        if files.unreadable:
            parts.append("cannot be read (too large or unreadable): " + ", ".join(files.unreadable))
        return _check(
            "asterisk.config.files",
            title,
            Status.UNVERIFIED,
            "infrastructure/asterisk/ was found, but "
            + "; ".join(parts)
            + ". The checks that need them are unverified.",
            "Restore the files from the repository (git status shows what is missing).",
        )
    optional = conf.FILES["ari"][0] if "ari" not in files.files else ""
    return _check(
        "asterisk.config.files",
        title,
        Status.PASS,
        "read "
        + ", ".join(found.name for found in files.files.values())
        + (f"; {optional} is not present" if optional else "")
        + ".",
    )


def _no_pstn_check(files: ConfigFiles, allowed: frozenset[str]) -> Check:
    title = "No PSTN, trunk or outbound route"
    findings = conf.pstn_findings(files, allowed)
    missing = [conf.FILES[logical][0] for logical in ("dialplan", "pjsip") if logical not in files.files]
    if not findings and missing:
        return _check(
            "asterisk.config.no_pstn",
            title,
            Status.UNVERIFIED,
            "no outbound route was found in what could be read, but " + ", ".join(missing) + " was not found, so a "
            "route there could not be ruled out.",
            "Run the doctor from a source checkout, or check that file by hand.",
        )
    return _verdict(
        "asterisk.config.no_pstn",
        title,
        findings,
        "no outbound or PSTN route: no trunk, outbound registration, source-address match or dial pattern, so a SIP "
        "client can only reach the local extensions. Local SIP is not a phone-number connection.",
    )


def _pjsip_check(files: ConfigFiles) -> Check:
    title = "SIP endpoints: authentication, codecs, identification"
    if "pjsip" not in files.files:
        return _unverified("asterisk.config.pjsip", title, "pjsip.conf.template was not found.")
    findings, count = conf.pjsip_findings(files)
    return _verdict(
        "asterisk.config.pjsip",
        title,
        findings,
        f"{count} endpoint(s): each requires authentication and is identified by user name only; G.711 only (ulaw, "
        "alaw); unauthenticated OPTIONS and SIP transfer are off.",
    )


def _credentials_check(files: ConfigFiles) -> Check:
    title = "No credential committed in the Asterisk configuration"
    if not {"pjsip", "dialplan"} & files.files.keys():
        return _unverified(
            "asterisk.config.credentials", title, "neither pjsip.conf.template nor extensions.conf was found."
        )
    return _verdict(
        "asterisk.config.credentials",
        title,
        conf.credential_findings(files),
        "every password and callback credential is a placeholder that is filled in from the environment when the "
        "container starts.",
    )


def _control_plane_check(files: ConfigFiles) -> Check:
    title = "ARI, AMI and the HTTP server are disabled"
    findings, disabled = conf.control_plane_findings(files)
    said = f" ({', '.join(disabled)} say enabled = no)" if disabled else ""
    return _verdict(
        "asterisk.config.control_plane",
        title,
        findings,
        "ARI, AMI and Asterisk's HTTP server are not enabled in the repository files"
        + said
        + ": Sparta controls calls "
        "through the dialplan's authenticated callbacks only.",
    )


def _modules_check(files: ConfigFiles) -> Check:
    title = "Module allow-list"
    if "modules" not in files.files:
        return _unverified("asterisk.config.modules", title, "modules.conf was not found.")
    findings, loaded = conf.module_findings(files)
    return _verdict(
        "asterisk.config.modules",
        title,
        findings,
        f"autoload is off and {loaded} modules are allow-listed: no control, shell or trunk module, and every module a "
        "call needs is loaded.",
    )


def _logging_check(files: ConfigFiles) -> Check:
    title = "Logging keeps the callback secret out of the logs"
    if not {"asterisk", "logger"} & files.files.keys():
        return _unverified("asterisk.config.logging", title, "neither asterisk.conf nor logger.conf was found.")
    return _verdict(
        "asterisk.config.logging",
        title,
        conf.logging_findings(files),
        "verbose and debug logging are off (they would print the dialplan's callback credential after expansion).",
    )


def _dialplan_extensions_check(settings: Settings, files: ConfigFiles) -> Check:
    title = "The dialplan serves the configured extensions"
    dialplan = files.files.get("dialplan")
    if dialplan is None:
        return _unverified("asterisk.config.extensions", title, "extensions.conf was not found.")
    defined, rung = conf.dialplan_literals(conf.dialplan_steps(dialplan.sections))
    sparta, owner = settings.asterisk_extension, settings.asterisk_owner_extension
    if sparta not in defined:
        return _check(
            "asterisk.config.extensions",
            title,
            Status.WARNING,
            f"{dialplan.name} defines no extension {sparta} (SPARTA_ASTERISK_EXTENSION). A call to it reaches Sparta "
            "only if a dial pattern matches, which this check does not evaluate.",
            f"Make the dialplan and SPARTA_ASTERISK_EXTENSION agree: add `exten => {sparta},1,...` or change the setting.",
        )
    if owner not in rung:
        return _check(
            "asterisk.config.extensions",
            title,
            Status.WARNING,
            f"{dialplan.name} defines extension {sparta}, but never rings extension {owner} "
            "(SPARTA_ASTERISK_OWNER_EXTENSION): Take Over would not reach the owner's phone.",
            f"Make the dialplan's Dial(PJSIP/{owner}) and SPARTA_ASTERISK_OWNER_EXTENSION agree.",
        )
    return _check(
        "asterisk.config.extensions",
        title,
        Status.PASS,
        f"{dialplan.name} defines extension {sparta} and rings extension {owner} for Take Over.",
    )


def _call_limits_check(files: ConfigFiles) -> Check:
    title = "Call limits enforced by the dialplan"
    dialplan = files.files.get("dialplan")
    if dialplan is None:
        return _unverified("asterisk.config.call_limits", title, "extensions.conf was not found.")
    timeout, group = conf.has_call_limits(conf.dialplan_steps(dialplan.sections))
    findings = []
    if not timeout:
        findings.append(
            Finding(
                Status.WARNING,
                dialplan.name,
                "no TIMEOUT(absolute): nothing at the Asterisk level ends a call that runs too long",
                "Add Set(TIMEOUT(absolute)=<seconds>) before the call is answered.",
            )
        )
    if not group:
        findings.append(
            Finding(
                Status.WARNING,
                dialplan.name,
                "no GROUP() limit: nothing at the Asterisk level caps concurrent calls",
                "Count calls with Set(GROUP()=...) and GROUP_COUNT(), and refuse when the limit is reached.",
            )
        )
    return _verdict(
        "asterisk.config.call_limits",
        title,
        findings,
        "the dialplan sets TIMEOUT(absolute) and counts calls with GROUP(), so Asterisk enforces a call length and a "
        "concurrency limit whatever Sparta does.",
    )


def config_checks(settings: Settings, files: ConfigFiles) -> list[Check]:
    first = files_check(files)
    if not files.directory:
        return [first]
    allowed = frozenset({"6000", "6001", "6002", settings.asterisk_extension, settings.asterisk_owner_extension})
    return [
        first,
        _no_pstn_check(files, allowed),
        _pjsip_check(files),
        _credentials_check(files),
        _control_plane_check(files),
        _modules_check(files),
        _logging_check(files),
        _dialplan_extensions_check(settings, files),
        _call_limits_check(files),
    ]


def asterisk_offline(settings: Settings, files: ConfigFiles) -> list[Check]:
    return [
        provider_check(settings),
        secret_check(settings),
        peers_check(settings),
        extensions_check(settings),
        limits_check(settings),
        *speech_checks_for(settings),
        *(openai_checks(settings) if settings.llm_provider == "azure_openai" else []),
        *config_checks(settings, files),
        media_format_check("asterisk"),
    ]
