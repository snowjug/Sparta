"""Static analysis of the Asterisk configuration kept in ``infrastructure/asterisk/`` (``sparta doctor --provider asterisk``).

Nothing here starts Asterisk or opens a socket: it reads the repository files and says what they would allow. A finding
never carries file content (a password committed by mistake must not be echoed by the tool that finds it): only a file
name, a line number and a fixed sentence.

The parser follows the parts of the Asterisk configuration syntax that matter here: ``;`` comments and ``;-- --;`` blocks,
``[section]`` headers with ``(!)`` templates and inheritance, ``key = value`` and ``key => value`` lines, and the dialplan's
``exten =>`` and ``same =>`` lines. Only the files named in :data:`FILES` are read: ``#include`` directives are not followed,
so a configuration that builds its endpoints that way is reported as not checkable, never as safe.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sparta.doctor.model import Status

DIRECTORY = ("infrastructure", "asterisk")
MAX_FILE_BYTES = 262_144
MAX_LINE_CHARS = 4096

# logical name -> the file names it may have in the repository (the first one found is used)
FILES: dict[str, tuple[str, ...]] = {
    "dialplan": ("extensions.conf", "extensions.conf.template"),
    "pjsip": ("pjsip.conf.template", "pjsip.conf"),
    "rtp": ("rtp.conf", "rtp.conf.template"),
    "modules": ("modules.conf", "modules.conf.template"),
    "ari": ("ari.conf.template", "ari.conf"),
    "http": ("http.conf", "http.conf.template"),
    "manager": ("manager.conf", "manager.conf.template"),
    "asterisk": ("asterisk.conf", "asterisk.conf.template"),
    "logger": ("logger.conf", "logger.conf.template"),
}
REQUIRED = ("dialplan", "pjsip", "rtp", "modules")

# What a call cannot do without, once ``autoload = no`` turns modules.conf into an allow-list.
REQUIRED_MODULES = (
    "res_pjsip",
    "res_pjsip_session",
    "chan_pjsip",
    "res_rtp_asterisk",
    "codec_ulaw",
    "codec_alaw",
    "pbx_config",
    "res_audiosocket",
    "app_audiosocket",
    "res_curl",
    "func_curl",
    "func_timeout",
    "func_groupcount",
)
# Modules that are a remote control surface, a shell, or a way out of the local network: (pattern, what it is, blocked?)
FORBIDDEN_MODULES: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (re.compile(r"res_ari\w*|res_stasis\w*|app_stasis"), "ARI", True),
    (
        re.compile(r"res_http_websocket|chan_websocket|res_http_post"),
        "the HTTP server's WebSocket and upload support",
        True,
    ),
    (re.compile(r"manager|res_manager\w*"), "AMI", True),
    (re.compile(r"res_agi|app_agi|app_externalivr"), "AGI", True),
    (re.compile(r"app_system|func_shell"), "shell commands", True),
    (re.compile(r"app_originate|app_page"), "outbound call origination", True),
    (
        re.compile(
            r"res_pjsip_outbound_\w+|res_pjsip_refer|chan_sip|chan_iax2|chan_dahdi|chan_motif|chan_mgcp|chan_skinny"
        ),
        "SIP trunks, transfers or another way to reach outside",
        True,
    ),
    (
        re.compile(r"app_voicemail\w*|app_queue|app_confbridge|app_meetme|app_followme"),
        "features Sparta does not use",
        False,
    ),
)

_TRUE = frozenset({"yes", "true", "1", "on", "y", "t"})
_FALSE = frozenset({"no", "false", "0", "off", "n", "f"})
_TRUNK_NAME = re.compile(r"trunk|pstn|carrier|itsp", re.IGNORECASE)
_PLACEHOLDER = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"  # ${NAME}
    r"|\$\{ENV\([A-Za-z_][A-Za-z0-9_]*\)\}"  # ${ENV(NAME)}
    r"|\$[A-Za-z_][A-Za-z0-9_]*"  # $NAME
    r"|@{1,2}[A-Za-z_][A-Za-z0-9_]*@{1,2}"  # @NAME@ and @@NAME@@
    r"|\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}"  # {{ NAME }}
)
_CONTAINS_PLACEHOLDER = re.compile(r"\$\{[^}]+\}|@{1,2}[A-Za-z_][A-Za-z0-9_]*@{1,2}")
_HEADER = re.compile(r"\[([^\]]*)\]\s*(?:\(([^)]*)\))?")
_DIGITS = re.compile(r"[0-9]{2,8}")
_DIAL = re.compile(r"(?<![A-Za-z0-9_$])(dial|originate|page)\s*\(", re.IGNORECASE)
_LOCAL_LEG = re.compile(r"PJSIP/([0-9]{2,8})", re.IGNORECASE)
_VARIABLE = re.compile(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)")
_TAINTED = re.compile(r"EXTEN|ARG[0-9]+|ARGC|CALLERID|CHANNEL|CONNECTEDLINE|DNID", re.IGNORECASE)
_USERPWD = re.compile(r"userpwd\s*\)?\s*=\s*(.*)", re.IGNORECASE)
_AUTH_HEADER = re.compile(r"authorization\s*:\s*(?:basic|bearer)\s+(.*)", re.IGNORECASE)
_SET_SECRET = re.compile(r"\bset\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", re.IGNORECASE)
_SECRET_NAME = re.compile(
    r"password|passwd|secret|token|pwd|credential|api_?key|(?<![A-Za-z])pass(?![A-Za-z])", re.IGNORECASE
)
_CREDENTIAL_KEYS = frozenset({"password", "md5_cred", "secret"})


# ---------------------------------------------------------------------------------------------------------- model
@dataclass(frozen=True)
class Item:
    line: int
    key: str
    value: str


@dataclass
class Section:
    name: str
    line: int
    template: bool = False
    parents: tuple[str, ...] = ()
    items: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigFile:
    name: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class ConfigFiles:
    """What was found in the directory. ``directory`` is False when there was no such directory to read."""

    directory: bool
    files: dict[str, ConfigFile]
    unreadable: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    severity: Status
    where: str  # "extensions.conf line 42"
    what: str  # a fixed sentence
    fix: str = ""


@dataclass(frozen=True)
class Step:
    context: str
    extension: str
    line: int
    text: str  # the application call, e.g. "Dial(PJSIP/6002,30,r)"


# -------------------------------------------------------------------------------------------------------- reading
def _exists(path: Path, *, directory: bool) -> bool:
    """``is_dir()`` / ``is_file()`` that answers False instead of raising when a parent cannot be searched."""
    try:
        return path.is_dir() if directory else path.is_file()
    except OSError:
        return False


def find_directory(explicit: Path | None = None) -> Path | None:
    """``infrastructure/asterisk`` of a source checkout: given, else found from the working directory or this file."""
    if explicit is not None:
        return explicit if _exists(explicit, directory=True) else None
    try:
        roots = [Path.cwd(), *Path.cwd().parents]
    except OSError:
        roots = []
    roots.extend(Path(__file__).resolve().parents)
    for root in roots:
        candidate = root.joinpath(*DIRECTORY)
        if _exists(candidate, directory=True):
            return candidate
    return None


def load(directory: Path | None) -> ConfigFiles:
    if directory is None:
        return ConfigFiles(False, {})
    files: dict[str, ConfigFile] = {}
    unreadable: list[str] = []
    for logical, names in FILES.items():
        for name in names:
            path = directory / name
            if not _exists(path, directory=False):
                continue
            try:
                text: str | None = (
                    path.read_text(encoding="utf-8-sig", errors="replace")
                    if path.stat().st_size <= MAX_FILE_BYTES
                    else None
                )
            except OSError:
                text = None
            if text is None:
                unreadable.append(name)
            else:
                files[logical] = ConfigFile(name, tuple(parse_conf(text)))
            break
    return ConfigFiles(True, files, tuple(unreadable))


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """``(line number, content)`` with ``;`` comments and ``;-- --;`` blocks removed and the content stripped."""
    out: list[tuple[int, str]] = []
    in_block = False
    for number, full in enumerate(text.splitlines(), start=1):
        raw = full[:MAX_LINE_CHARS]
        kept: list[str] = []
        i = 0
        while i < len(raw):
            if in_block:
                end = raw.find("--;", i)
                if end < 0:
                    break
                in_block = False
                i = end + 3
            elif raw.startswith("\\;", i):
                kept.append(";")
                i += 2
            elif raw.startswith(";--", i):
                in_block = True
                i += 3
            elif raw[i] == ";":
                break
            else:
                kept.append(raw[i])
                i += 1
        out.append((number, "".join(kept).strip()))
    return out


def parse_conf(text: str) -> list[Section]:
    sections: list[Section] = []
    current: Section | None = None
    for number, line in _logical_lines(text):
        if not line or line.startswith("#"):
            continue  # blank, or an #include / #exec directive
        header = _HEADER.match(line) if line.startswith("[") else None
        if header:
            modifiers = [m.strip() for m in (header.group(2) or "").split(",") if m.strip()]
            name = header.group(1).strip()
            if "+" in modifiers:
                earlier = next((s for s in reversed(sections) if s.name == name), None)
                if earlier is not None:
                    current = earlier
                    continue
            parents = tuple(m for m in modifiers if m not in ("!", "+"))
            current = Section(name, number, "!" in modifiers, parents)
            sections.append(current)
            continue
        item = _split_item(line)
        if item is not None and current is not None:
            current.items.append(Item(number, item[0], item[1]))
    return sections


def _split_item(line: str) -> tuple[str, str] | None:
    """``key = value`` or ``key => value`` at the first ``=`` (no regular expression: a long line cannot make it slow)."""
    position = line.find("=")
    if position <= 0:
        return None
    key = line[:position].strip()
    rest = line[position + 1 :]
    if rest.startswith(">"):
        rest = rest[1:]
    return (key, rest.strip()) if key else None


def _templates(sections: Sequence[Section]) -> dict[str, Section]:
    found: dict[str, Section] = {s.name: s for s in sections if s.template}
    for section in sections:
        found.setdefault(section.name, section)
    return found


def effective_items(section: Section, templates: dict[str, Section], _seen: frozenset[str] = frozenset()) -> list[Item]:
    """The section's items with those it inherits from its templates first (the section's own lines win)."""
    inherited: list[Item] = []
    for parent_name in section.parents:
        parent = templates.get(parent_name)
        if parent is not None and parent_name not in _seen:
            inherited.extend(effective_items(parent, templates, _seen | {section.name}))
    return [*inherited, *section.items]


def _last(items: Sequence[Item], key: str) -> Item | None:
    found: Item | None = None
    for item in items:
        if item.key.lower() == key:
            found = item
    return found


def _truthy(value: str) -> bool | None:
    lowered = value.strip().lower()
    return True if lowered in _TRUE else False if lowered in _FALSE else None


def _is_placeholder(value: str) -> bool:
    stripped = value.strip()
    return not stripped or _PLACEHOLDER.fullmatch(stripped) is not None


# ------------------------------------------------------------------------------------------------------- dialplan
def dialplan_steps(sections: Sequence[Section]) -> list[Step]:
    steps: list[Step] = []
    for section in sections:
        if section.name.lower() in ("general", "globals"):
            continue
        extension = ""
        for item in section.items:
            key = item.key.lower()
            if key == "exten":
                parts = item.value.split(",", 2)
                if len(parts) == 3:
                    extension = parts[0].strip()
                    steps.append(Step(section.name, extension, item.line, parts[2].strip()))
            elif key == "same" and extension:
                parts = item.value.split(",", 1)
                if len(parts) == 2:
                    steps.append(Step(section.name, extension, item.line, parts[1].strip()))
    return steps


def _first_argument(text: str, start: int) -> str:
    depth = 0
    out: list[str] = []
    for ch in text[start:]:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        out.append(ch)
    return "".join(out).strip()


def _legs(target: str) -> list[str]:
    legs: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in target:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth = max(0, depth - 1)
        if ch == "&" and depth == 0:
            legs.append("".join(current))
            current = []
        else:
            current.append(ch)
    legs.append("".join(current))
    return [leg.strip() for leg in legs if leg.strip()]


def _without_variables(text: str) -> str:
    for _ in range(10):
        replaced = re.sub(r"\$\{[^{}]*\}", "V", text)
        if replaced == text:
            break
        text = replaced
    return text


_DIAL_FIX = (
    "Dial only literal local extensions, such as Dial(PJSIP/6002): never build a target from the dialled number."
)


def _dial_findings(where: str, step: Step, allowed: frozenset[str]) -> list[Finding]:
    out: list[Finding] = []
    for call in _DIAL.finditer(step.text):
        for leg in _legs(_first_argument(step.text, call.end())):
            literal = _LOCAL_LEG.fullmatch(leg)
            plain = _without_variables(leg)
            dynamic = "${" in leg
            if literal:
                if literal.group(1) not in allowed:
                    out.append(
                        Finding(
                            Status.WARNING,
                            where,
                            "Dial() rings an extension that is not one of the configured local extensions",
                            "Dial only the extensions in SPARTA_ASTERISK_EXTENSION and SPARTA_ASTERISK_OWNER_EXTENSION.",
                        )
                    )
            elif plain.upper().startswith("PJSIP/") and ("@" in plain[6:] or "/" in plain[6:]):
                out.append(
                    Finding(
                        Status.BLOCKED,
                        where,
                        "Dial() reaches its target through a named endpoint (trunk style)",
                        _DIAL_FIX,
                    )
                )
            elif dynamic:
                tainted = any(_TAINTED.fullmatch(name) for name in _VARIABLE.findall(leg))
                dials_itself = leg.upper() == "PJSIP/${EXTEN}" and step.extension in allowed
                if tainted and not dials_itself:
                    out.append(
                        Finding(
                            Status.BLOCKED,
                            where,
                            "Dial() builds its target from the dialled number outside the fixed local extensions "
                            "(a wildcard or pattern route out)",
                            _DIAL_FIX,
                        )
                    )
                elif not tainted:
                    out.append(
                        Finding(
                            Status.WARNING,
                            where,
                            "Dial() has a target that is not a literal, so it cannot be checked here",
                            "Check by hand that it can only ever be a local extension, or write it literally.",
                        )
                    )
            elif plain.upper().startswith("PJSIP/"):
                out.append(
                    Finding(
                        Status.WARNING,
                        where,
                        "Dial() rings an endpoint that is not a numeric local extension",
                        _DIAL_FIX,
                    )
                )
            else:
                out.append(
                    Finding(
                        Status.BLOCKED,
                        where,
                        "Dial() uses a channel type other than PJSIP, or none",
                        _DIAL_FIX,
                    )
                )
    return out


def dialplan_literals(steps: Sequence[Step]) -> tuple[set[str], set[str]]:
    """``(extensions defined literally, local extensions the dialplan rings)``."""
    defined = {s.extension for s in steps if _DIGITS.fullmatch(s.extension)}
    rung: set[str] = set()
    for step in steps:
        for call in _DIAL.finditer(step.text):
            for leg in _legs(_first_argument(step.text, call.end())):
                if literal := _LOCAL_LEG.fullmatch(leg):
                    rung.add(literal.group(1))
    return defined, rung


def has_call_limits(steps: Sequence[Step]) -> tuple[bool, bool]:
    """``(TIMEOUT(absolute) is set, a GROUP() limit is used)``."""
    timeout = any(re.search(r"TIMEOUT\s*\(\s*absolute\s*\)", s.text, re.IGNORECASE) for s in steps)
    group = any(re.search(r"(?<![A-Za-z0-9_])GROUP(?:_COUNT)?\s*\(", s.text, re.IGNORECASE) for s in steps)
    return timeout, group


# ----------------------------------------------------------------------------------------------- no route to the PSTN
def pstn_findings(files: ConfigFiles, allowed: frozenset[str]) -> list[Finding]:
    out: list[Finding] = []
    dialplan = files.files.get("dialplan")
    if dialplan is not None:
        for step in dialplan_steps(dialplan.sections):
            out.extend(_dial_findings(f"{dialplan.name} line {step.line}", step, allowed))
    pjsip = files.files.get("pjsip")
    if pjsip is not None:
        templates = _templates(pjsip.sections)
        for section in pjsip.sections:
            where = f"{pjsip.name} line {section.line}"
            kind = _last(effective_items(section, templates), "type")
            kind_name = kind.value.strip().lower() if kind else ""
            if kind_name == "registration":
                out.append(
                    Finding(
                        Status.BLOCKED,
                        where,
                        "outbound registration (a SIP trunk to a provider)",
                        "Remove it: Sparta's Asterisk has no trunk and no phone-network route.",
                    )
                )
            if kind_name == "identify":
                out.append(
                    Finding(
                        Status.BLOCKED,
                        where,
                        "identification by source address (type=identify), which is how a trunk is matched",
                        "Remove it: callers are identified by authenticating as a local extension.",
                    )
                )
            if _TRUNK_NAME.search(section.name):
                out.append(Finding(Status.BLOCKED, where, "a section named like a trunk or carrier", "Remove it."))
            for item in section.items:
                if item.key.lower() in ("outbound_auth", "server_uri", "client_uri"):
                    out.append(
                        Finding(
                            Status.BLOCKED,
                            f"{pjsip.name} line {item.line}",
                            "an outbound credential or registration target (a trunk-style setting)",
                            "Remove it.",
                        )
                    )
    return out


# ------------------------------------------------------------------------------------------------------- PJSIP
def _codecs(items: Sequence[Item]) -> tuple[frozenset[str], bool]:
    """``(codecs left allowed, disallow=all came before the first allow)`` after the lines are applied in order."""
    allowed: set[str] = set()
    cleared_first = False
    seen_allow = False
    for item in items:
        key = item.key.lower()
        names = [name.strip().lower() for name in item.value.split(",") if name.strip()]
        if key == "disallow":
            for name in names:
                if name == "all":
                    allowed.clear()
                    cleared_first = cleared_first or not seen_allow
                else:
                    allowed.discard(name)
        elif key == "allow":
            seen_allow = True
            for name in names:
                if name == "!all":
                    allowed.clear()
                elif name.startswith("!"):
                    allowed.discard(name[1:])
                else:
                    allowed.add(name)
    return frozenset(allowed), cleared_first


def pjsip_findings(files: ConfigFiles) -> tuple[list[Finding], int]:
    """Hardening problems of the endpoints, and how many endpoints were judged."""
    pjsip = files.files["pjsip"]
    templates = _templates(pjsip.sections)

    def kind_of(section: Section) -> str:
        item = _last(effective_items(section, templates), "type")
        return item.value.strip().lower() if item else ""

    endpoints = [s for s in pjsip.sections if kind_of(s) == "endpoint"]
    judged = [s for s in endpoints if not s.template] or endpoints
    out: list[Finding] = []
    seen: set[str] = set()

    def add(finding: Finding) -> None:
        if finding.what not in seen:
            seen.add(finding.what)
            out.append(finding)

    for section in judged:
        items = effective_items(section, templates)
        where = f"{pjsip.name} line {section.line}"
        auth = _last(items, "auth")
        if not section.template and (auth is None or not auth.value.strip()):
            add(
                Finding(
                    Status.BLOCKED,
                    where,
                    "an endpoint without auth, so it would accept calls without credentials",
                    "Give every endpoint an auth object: there must be no anonymous endpoint.",
                )
            )
        if section.name.lower().split("@")[0] == "anonymous":
            add(
                Finding(
                    Status.BLOCKED,
                    where,
                    "an endpoint named anonymous, which accepts calls from unidentified sources",
                    "Remove it.",
                )
            )
        identify = _last(items, "identify_by")
        if identify is None:
            add(
                Finding(
                    Status.WARNING,
                    where,
                    "identify_by is not set (the default also matches on the authentication user name)",
                    "Set identify_by = username on the endpoint.",
                )
            )
        else:
            methods = {m.strip().lower() for m in identify.value.split(",") if m.strip()}
            if methods - {"username"}:
                widened = methods & {"ip", "header", "request_uri"}
                add(
                    Finding(
                        Status.BLOCKED if widened else Status.WARNING,
                        f"{pjsip.name} line {identify.line}",
                        "identify_by matches callers by more than their user name",
                        "Set identify_by = username.",
                    )
                )
        allowed, cleared_first = _codecs(items)
        if allowed != {"ulaw", "alaw"}:
            add(
                Finding(
                    Status.WARNING,
                    where,
                    "the allowed codecs are not exactly ulaw and alaw",
                    "Use disallow = all, then allow = ulaw and allow = alaw: G.711 is what the media bridge expects.",
                )
            )
        elif not cleared_first:
            add(
                Finding(
                    Status.WARNING,
                    where,
                    "allow comes before disallow = all, so the codec list depends on Asterisk's defaults",
                    "Put disallow = all before the allow lines.",
                )
            )
        transfer = _last(items, "allow_transfer")
        if transfer is None or _truthy(transfer.value) is not False:
            add(
                Finding(
                    Status.WARNING,
                    where,
                    "SIP transfer is not switched off (allow_transfer)",
                    "Set allow_transfer = no: take-over is a new call leg, not a SIP REFER.",
                )
            )
    if not judged:
        add(
            Finding(
                Status.UNVERIFIED,
                pjsip.name,
                "no endpoint section was found (they may be generated when the container starts)",
                "Check the rendered pjsip.conf by hand.",
            )
        )
    unauthenticated = [
        (item, _truthy(item.value))
        for section in pjsip.sections
        for item in section.items
        if item.key.lower() == "allow_unauthenticated_options"
    ]
    if any(value is True for _, value in unauthenticated):
        item = next(i for i, value in unauthenticated if value is True)
        add(
            Finding(
                Status.BLOCKED,
                f"{pjsip.name} line {item.line}",
                "unauthenticated SIP OPTIONS are allowed",
                "Set allow_unauthenticated_options = no.",
            )
        )
    elif judged and not any(value is False for _, value in unauthenticated):
        add(
            Finding(
                Status.WARNING,
                pjsip.name,
                "allow_unauthenticated_options = no is not written anywhere",
                "Add allow_unauthenticated_options = no to the endpoints (it is Asterisk's default, so say it).",
            )
        )
    for section in pjsip.sections:
        order = _last(section.items, "endpoint_identifier_order")
        if order is not None and order.value.strip().lower() != "username":
            add(
                Finding(
                    Status.WARNING,
                    f"{pjsip.name} line {order.line}",
                    "endpoint_identifier_order allows more than identification by user name",
                    "Set endpoint_identifier_order = username.",
                )
            )
    return out, len(judged)


# ------------------------------------------------------------------------------------------------------ credentials
def credential_findings(files: ConfigFiles) -> list[Finding]:
    """A literal credential (not a placeholder that is filled in at start-up) written into a committed file."""
    fix = "Write a placeholder such as ${NAME} or @@NAME@@ and supply the value from the environment."

    def literal(where: str) -> Finding:
        return Finding(Status.BLOCKED, where, "a literal credential is committed", fix)

    out: list[Finding] = []
    for logical in ("pjsip", "ari", "http", "manager"):
        found = files.files.get(logical)
        if found is not None:
            out.extend(
                literal(f"{found.name} line {item.line}")
                for section in found.sections
                for item in section.items
                if item.key.lower() in _CREDENTIAL_KEYS and not _is_placeholder(item.value)
            )
    dialplan = files.files.get("dialplan")
    if dialplan is None:
        return out
    out.extend(
        literal(f"{dialplan.name} line {item.line}")
        for section in dialplan.sections
        if section.name.lower() == "globals"
        for item in section.items
        if _SECRET_NAME.search(item.key) and not _is_placeholder(item.value)
    )
    for step in dialplan_steps(dialplan.sections):
        where = f"{dialplan.name} line {step.line}"
        userpwd = _USERPWD.search(step.text)
        if userpwd and not _CONTAINS_PLACEHOLDER.search(userpwd.group(1).split(":", 1)[-1]):
            out.append(literal(where))
        header = _AUTH_HEADER.search(step.text)
        if header and not _CONTAINS_PLACEHOLDER.search(header.group(1)):
            out.append(literal(where))
        for assignment in _SET_SECRET.finditer(step.text):
            value = assignment.group(2).strip().rstrip(")").strip()
            if (
                _SECRET_NAME.search(assignment.group(1))
                and value
                and not _CONTAINS_PLACEHOLDER.search(assignment.group(2))
            ):
                out.append(literal(where))
    return out


# ------------------------------------------------------------------------------------------------ control plane
def control_plane_findings(files: ConfigFiles) -> tuple[list[Finding], list[str]]:
    """ARI, AMI and the HTTP server must be off. Returns the problems and the files that say so explicitly."""
    out: list[Finding] = []
    disabled: list[str] = []
    for logical, label, default_on in (
        ("ari", "ARI", True),
        ("http", "the HTTP server", False),
        ("manager", "AMI", False),
    ):
        found = files.files.get(logical)
        if found is None:
            continue
        state: Item | None = None
        for section in found.sections:
            if section.name.lower() == "general":
                state = _last(section.items, "enabled") or state
        value = _truthy(state.value) if state is not None else None
        if state is not None and value is True:
            out.append(
                Finding(
                    Status.BLOCKED,
                    f"{found.name} line {state.line}",
                    f"{label} is enabled",
                    "Set enabled = no: Sparta uses neither a control API nor Asterisk's HTTP server.",
                )
            )
        elif value is False:
            disabled.append(found.name)
        elif default_on:
            out.append(
                Finding(
                    Status.WARNING,
                    found.name,
                    f"{label} is not explicitly disabled (it is on unless it says otherwise)",
                    "Set enabled = no in [general].",
                )
            )
    return out, disabled


def module_findings(files: ConfigFiles) -> tuple[list[Finding], int]:
    """modules.conf as an allow-list: no control or trunk module, and every module a call needs. Also the number loaded."""
    modules = files.files["modules"]
    loaded: list[tuple[int, str]] = []
    skipped: set[str] = set()
    autoload: Item | None = None
    for section in modules.sections:
        for item in section.items:
            key = item.key.lower()
            name = item.value.strip().lower().removesuffix(".so")
            if key in ("load", "preload"):
                loaded.append((item.line, name))
            elif key == "noload":
                skipped.add(name)
            elif key == "autoload":
                autoload = item
    out: list[Finding] = []
    seen: set[str] = set()
    for line, name in loaded:
        for pattern, label, blocked in FORBIDDEN_MODULES:
            if pattern.fullmatch(name) and label not in seen:
                seen.add(label)
                out.append(
                    Finding(
                        Status.BLOCKED if blocked else Status.WARNING,
                        f"{modules.name} line {line}",
                        f"a module for {label} is loaded",
                        "Remove it from modules.conf: Sparta's Asterisk is an allow-list of what a local SIP call needs.",
                    )
                )
    allow_list = autoload is not None and _truthy(autoload.value) is False
    if not allow_list:
        out.append(
            Finding(
                Status.WARNING,
                modules.name,
                "autoload is not switched off, so every module on disk loads unless a noload line names it",
                "Set autoload = no under [modules] and load only what a call needs.",
            )
        )
    else:
        names = {name for _, name in loaded}
        missing = [name for name in REQUIRED_MODULES if name not in names]
        if missing:
            out.append(
                Finding(
                    Status.BLOCKED,
                    modules.name,
                    "modules a call needs are not loaded: " + ", ".join(missing),
                    "Add a load line for each of them to modules.conf.",
                )
            )
    return out, len(loaded)


def logging_findings(files: ConfigFiles) -> list[Finding]:
    """Verbose and debug logging print dialplan arguments after expansion, which includes the callback secret."""
    out: list[Finding] = []
    fix = "Keep verbose at 0 and debug at 0 in asterisk.conf, and leave verbose and debug out of logger.conf."
    options = files.files.get("asterisk")
    if options is not None:
        for section in options.sections:
            if section.name.lower() != "options":
                continue
            for item in section.items:
                key, value = item.key.lower(), item.value.strip()
                digits = re.match(r"[0-9]+", value)
                level = int(digits.group()) if digits else 0
                if (key == "verbose" and level >= 3) or (key == "debug" and (level > 0 or _truthy(value) is True)):
                    out.append(
                        Finding(
                            Status.BLOCKED,
                            f"{options.name} line {item.line}",
                            f"{key} logging would write the callback secret into the log",
                            fix,
                        )
                    )
    logger = files.files.get("logger")
    if logger is not None:
        for section in logger.sections:
            if section.name.lower() != "logfiles":
                continue
            for item in section.items:
                levels = {re.sub(r"\(.*\)", "", name).strip().lower() for name in item.value.split(",")}
                if levels & {"verbose", "debug", "*"}:
                    out.append(
                        Finding(
                            Status.BLOCKED,
                            f"{logger.name} line {item.line}",
                            "a log file takes verbose or debug messages, which print the callback secret",
                            fix,
                        )
                    )
    return out


def rtp_range(files: ConfigFiles) -> tuple[int, int] | None:
    found = files.files.get("rtp")
    if found is None:
        return None
    start = end = None
    for section in found.sections:
        for item in section.items:
            if item.key.lower() == "rtpstart" and item.value.strip().isdigit():
                start = int(item.value)
            elif item.key.lower() == "rtpend" and item.value.strip().isdigit():
                end = int(item.value)
    return (start, end) if start is not None and end is not None and start <= end <= 65535 else None
