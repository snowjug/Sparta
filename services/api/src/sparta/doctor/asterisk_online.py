"""Network probes of ``sparta doctor --provider asterisk --online``: is anything there, without a phone?

Three questions, all free and none of them a call:

* does a SIP service answer on the configured UDP port? One ``OPTIONS`` request, no credentials, no retransmission;
* does anything accept a TCP connection on the media port? A connect that is closed at once, with nothing sent;
* the RTP ports cannot be probed from here at all, so that check only says how to prove them.

A probe never raises: a failure becomes a check with a static reason. Text a remote service sent is never shown except one
short printable-ASCII ``Server`` header.
"""

import asyncio
import contextlib
import ipaddress
import re
import secrets
import socket
from dataclasses import dataclass

from sparta.config import Settings
from sparta.doctor.asterisk import plain_host
from sparta.doctor.checks import ASTERISK
from sparta.doctor.model import Check, Status

SIP_WAIT_S = 4.0
MEDIA_WAIT_S = 4.0
SIP_RESPONSE = re.compile(rb"SIP/2\.0 ([1-6][0-9]{2})(?: [^\r\n]*)?\r?\n")
SIP_HOST = re.compile(r"[A-Za-z0-9._\-:\[\]%]{1,255}")


@dataclass(frozen=True)
class SipOutcome:
    kind: str  # answered | garbage | silent | refused | unresolved | invalid | error
    status: int = 0
    server: str = ""


def _uri_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def options_request(target: str, local: tuple[str, int]) -> bytes:
    """A minimal SIP ``OPTIONS`` (RFC 3261): fresh Call-ID, branch and tag every time, and no credential of any kind."""
    via = _uri_host(local[0].split("%", 1)[0])
    lines = [
        f"OPTIONS sip:{_uri_host(target)} SIP/2.0",
        f"Via: SIP/2.0/UDP {via}:{local[1]};branch=z9hG4bK{secrets.token_hex(8)};rport",
        "Max-Forwards: 70",
        f"From: <sip:sparta-doctor@{via}>;tag={secrets.token_hex(6)}",
        f"To: <sip:{_uri_host(target)}>",
        f"Call-ID: {secrets.token_hex(12)}@{via}",
        "CSeq: 1 OPTIONS",
        "User-Agent: sparta-doctor",
        "Accept: application/sdp",
        "Content-Length: 0",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def _printable(value: bytes, limit: int = 40) -> str:
    return "".join(ch if ch.isascii() and ch.isprintable() else "?" for ch in value.decode("latin-1"))[:limit]


def probe_sip_options(host: str, port: int, timeout_s: float) -> SipOutcome:
    """Send one OPTIONS datagram and read the first datagram that comes back. Blocking: run it in a thread."""
    if not SIP_HOST.fullmatch(host):
        return SipOutcome("invalid")
    try:
        infos = socket.getaddrinfo(host.strip("[]"), port, type=socket.SOCK_DGRAM)
    except (socket.gaierror, UnicodeError):
        return SipOutcome("unresolved")
    if not infos:
        return SipOutcome("unresolved")
    family, socktype, proto, _, address = min(infos, key=lambda info: info[0] != socket.AF_INET)
    try:
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(timeout_s)
            sock.connect(address)  # a connected UDP socket sees an ICMP "port unreachable" as a refusal
            sock.send(options_request(host, sock.getsockname()[:2]))
            data = sock.recv(4096)
    except TimeoutError:
        return SipOutcome("silent")
    except (ConnectionRefusedError, ConnectionResetError):
        return SipOutcome("refused")
    except OSError:
        return SipOutcome("error")
    answer = SIP_RESPONSE.match(data)
    if answer is None:
        return SipOutcome("garbage")
    header = re.search(rb"(?im)^(?:server|user-agent):[ \t]*([^\r\n]{1,80})", data)
    return SipOutcome("answered", int(answer.group(1)), _printable(header.group(1)) if header else "")


async def sip_check(settings: Settings, timeout_s: float) -> Check:
    title = "SIP service answers"
    host, port = settings.asterisk_sip_host, settings.asterisk_sip_port
    wait = min(timeout_s, SIP_WAIT_S)
    outcome = await asyncio.to_thread(probe_sip_options, host, port, wait)
    where = f"{plain_host(host)}:{port}"
    reach = (
        "Is the Asterisk container up (`docker compose --profile asterisk ps`) and is UDP port "
        f"{port} published on that address (docker-compose.yml)? Does a firewall drop UDP? "
        "If SPARTA_ASTERISK_SIP_HOST or SPARTA_ASTERISK_SIP_PORT is not where Asterisk listens, correct it."
    )
    if outcome.kind == "answered":
        wants = " (it wants credentials, as expected: none were sent)" if outcome.status in (401, 403) else ""
        who = f" It identifies itself as {outcome.server!r}." if outcome.server else ""
        return Check(
            "asterisk.sip_options",
            ASTERISK,
            title,
            Status.PASS,
            f"the SIP service at {where} answered one OPTIONS request with status {outcome.status}{wants}.{who} That "
            "proves something speaks SIP there, not that a phone can register or hear audio.",
            keep_numbers=True,
        )
    reasons = {
        "garbage": f"a reply came from {where}, but it was not a SIP response: something other than a SIP server may use that port",
        "silent": f"no SIP answer from {where} within {wait:g} s (one OPTIONS request, no retransmission)",
        "refused": f"{where} refused the datagram (port unreachable): nothing listens on that UDP port",
        "unresolved": "the host name of SPARTA_ASTERISK_SIP_HOST could not be resolved",
        "invalid": "SPARTA_ASTERISK_SIP_HOST is not a host name or address",
        "error": f"a network error occurred while sending to {where}",
    }
    return Check(
        "asterisk.sip_options",
        ASTERISK,
        title,
        Status.BLOCKED,
        reasons[outcome.kind] + ".",
        reach + " Run the doctor again to rule out a lost datagram.",
        keep_numbers=True,
    )


def probe_host(bind: str) -> str:
    """Where to connect to reach a listener bound to ``bind``: the loopback address when it listens on every address."""
    value = bind.strip().strip("[]")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return value
    if address.is_unspecified:
        return "::1" if address.version == 6 else "127.0.0.1"
    return value


async def media_check(settings: Settings, timeout_s: float) -> Check:
    """Connect and close at once, sending nothing: the peer allow-list may drop this host, which is not a failure."""
    title = "Media listener (AudioSocket)"
    port = settings.asterisk_media_port
    where = f"{plain_host(probe_host(settings.asterisk_media_bind))}:{port}"
    if port == 0:
        return Check(
            "asterisk.media_listener",
            ASTERISK,
            title,
            Status.UNVERIFIED,
            "SPARTA_ASTERISK_MEDIA_PORT is 0 (a random port is chosen when the API starts), so there is no fixed port to probe.",
            "Use a fixed port (8090 by default) for a real deployment.",
            keep_numbers=True,
        )
    wait = min(timeout_s, MEDIA_WAIT_S)
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(probe_host(settings.asterisk_media_bind), port), wait
        )
    except ConnectionRefusedError:
        return Check(
            "asterisk.media_listener",
            ASTERISK,
            title,
            Status.UNVERIFIED,
            f"nothing listens on {where}: the API is not running, so nothing listens yet (or it runs in a container that "
            "does not publish this port, which is how Docker Compose is set up).",
            "Start the API with SPARTA_TELEPHONY_PROVIDER=asterisk: it opens this listener at start-up. Run the doctor "
            "again, from the same machine or network as the API, to see it answer.",
            keep_numbers=True,
        )
    except (TimeoutError, OSError) as exc:
        why = (
            f"no answer from {where} within {wait:g} s"
            if isinstance(exc, TimeoutError)
            else f"could not connect to {where} ({type(exc).__name__})"
        )
        return Check(
            "asterisk.media_listener",
            ASTERISK,
            title,
            Status.WARNING,
            why + ".",
            "Check the address in SPARTA_ASTERISK_MEDIA_BIND, the port in SPARTA_ASTERISK_MEDIA_PORT and any firewall.",
            keep_numbers=True,
        )
    writer.close()
    with contextlib.suppress(OSError, asyncio.TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), 1.0)
    return Check(
        "asterisk.media_listener",
        ASTERISK,
        title,
        Status.PASS,
        f"something accepted a TCP connection on {where}, which was closed at once with nothing sent. The API logs one "
        "'media connection refused' warning for it (it was not an AudioSocket handshake), and its peer allow-list may "
        "also drop a connection from this host: neither is a fault. Only Asterisk's own connection proves the path.",
        keep_numbers=True,
    )


def rtp_check(rtp: tuple[int, int] | None) -> Check:
    where = f"UDP ports {rtp[0]} to {rtp[1]} (from rtp.conf)" if rtp else "the UDP range set in rtp.conf"
    return Check(
        "asterisk.rtp_ports",
        ASTERISK,
        "RTP media ports",
        Status.UNVERIFIED,
        f"the audio of a call travels as RTP over {where} between the SIP client and Asterisk. Nothing run from here can "
        "show that a phone's audio gets through them.",
        "Register a SIP client, call the Sparta extension and listen for the assistant (docs/ANDROID_SIP_TESTING.md). If "
        "the call connects but one side hears nothing, publish exactly that UDP range (docker-compose.yml), allow it through "
        "the firewall and, for a phone on the Wi-Fi, set SPARTA_ASTERISK_EXTERNAL_IP to this machine's LAN address.",
        keep_numbers=True,
    )


async def asterisk_online(settings: Settings, timeout_s: float, rtp: tuple[int, int] | None = None) -> list[Check]:
    sip, media = await asyncio.gather(sip_check(settings, timeout_s), media_check(settings, timeout_s))
    return [sip, media, rtp_check(rtp)]
