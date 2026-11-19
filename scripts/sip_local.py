#!/usr/bin/env python3
"""Local SIP helper: generate the development secrets once, and show how to register a SIP client.

    python scripts/sip_local.py init            # write .env (provider + callback secret) and .env.sip (SIP passwords)
    python scripts/sip_local.py init --speech fake   # tone-coded test speech instead of local Whisper/Piper
    python scripts/sip_local.py show            # server address and extensions for a SIP client (passwords hidden)
    python scripts/sip_local.py show --reveal   # the same, and print the SIP passwords so you can type them into the phone

Standard library only. Secrets are random (``secrets`` module), written with owner-only permissions where the platform has
them, never printed by ``init`` (or by ``show`` unless you ask with ``--reveal``), and never committed (``.env`` and ``.env.*``
are git-ignored). Existing values are kept unless ``--force`` is given. The passwords protect a SIP phone on your own network:
they are development credentials.
"""

import argparse
import contextlib
import os
import secrets
import socket
import stat
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALPHABET = string.ascii_letters + string.digits
MARK = "# --- local SIP (scripts/sip_local.py) ---"


def password(length: int = 32) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def write_env(path: Path, entries: dict[str, str], header: str) -> None:
    """Append ``entries`` (only keys not already present) to ``path`` in one block, atomically, owner-only."""
    existing = read_env(path)
    new = {k: v for k, v in entries.items() if k not in existing}
    if not new:
        return
    body = path.read_text(encoding="utf-8") if path.exists() else ""
    if body and not body.endswith("\n"):
        body += "\n"
    block = f"\n{header}\n" + "".join(f"{key}={value}\n" for key, value in new.items())
    temp = path.with_name(path.name + ".tmp")
    # Created owner-only from the first byte (a write followed by a chmod would leave a readable window), then moved into place.
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body + block)
    with contextlib.suppress(OSError, NotImplementedError):
        temp.chmod(stat.S_IRUSR | stat.S_IWUSR)  # in case the temp file already existed with wider permissions
    os.replace(temp, path)


def lan_address() -> str:
    """This machine's primary LAN address (no packet is sent: a UDP 'connect' only selects the outgoing interface)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def cmd_init(args: argparse.Namespace) -> int:
    env_path, sip_path = ROOT / ".env", ROOT / ".env.sip"
    if args.force:
        for path in (env_path, sip_path):
            current = read_env(path)
            for key in list(current):
                if key.startswith(("SPARTA_ASTERISK_WEBHOOK_SECRET", "SIP_PASSWORD_")):
                    # drop the old secret lines so fresh ones are written below
                    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(key + "=")]
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    speech = {"local": "local", "fake": "fake", "azure": "azure"}[args.speech]
    entries = {
        "SPARTA_TELEPHONY_PROVIDER": "asterisk",
        "SPARTA_STT_PROVIDER": speech,
        "SPARTA_TTS_PROVIDER": speech,
        "SPARTA_ASTERISK_WEBHOOK_SECRET": secrets.token_urlsafe(32),
    }
    if speech == "local":
        entries["SPARTA_LOCAL_SPEECH"] = "1"  # the compose build adds the local speech engines to the API image
    write_env(env_path, entries, MARK)
    write_env(sip_path, {"SIP_PASSWORD_6001": password(), "SIP_PASSWORD_6002": password()}, MARK)
    print(f"Wrote {env_path.name} and {sip_path.name} (new secrets generated; existing values kept).")
    print("Both files are git-ignored. Nothing secret was printed.")
    if speech == "local":
        print("Next: 1. download the free speech models (about 650 MB, every file checked against a pinned SHA-256):")
        print("         cd services/api && python -m sparta models fetch")
        print(
            "      2. docker compose --profile asterisk up --build    (the first build adds the local speech engines)"
        )
    else:
        print("Next: docker compose --profile asterisk up --build")
    print("Then register a SIP client: python scripts/sip_local.py show --reveal")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    env, sip = read_env(ROOT / ".env"), read_env(ROOT / ".env.sip")
    if not sip.get("SIP_PASSWORD_6001"):
        print("No SIP credentials yet. Run: python scripts/sip_local.py init", file=sys.stderr)
        return 1
    bind = env.get("SPARTA_ASTERISK_BIND", "127.0.0.1")
    external = env.get("SPARTA_ASTERISK_EXTERNAL_IP", "")
    host = external or (lan_address() if bind in ("0.0.0.0", "") else bind)  # noqa: S104 - a comparison, not a bind
    port = env.get("SPARTA_ASTERISK_SIP_PORT", "5060")
    print("Local SIP server (Asterisk) - register a SIP client with:")
    print(f"  Domain / server : {host}:{port}   transport: UDP   (no outbound proxy, no STUN, no ICE)")
    print("  Audio codecs    : PCMU (G.711 u-law) or PCMA; leave Opus/G.722 off")
    for ext, label in (
        ("6001", "the test caller (dial 6000 to reach Sparta)"),
        ("6002", "the owner's phone (rung on Take Over)"),
    ):
        pw = sip.get(f"SIP_PASSWORD_{ext}", "")
        print(f"  Username {ext}  : {label}")
        print(f"  Password {ext}  : {pw if args.reveal else '(hidden: run with --reveal to print it)'}")
    if bind in ("127.0.0.1", "localhost") and not external:
        print("\nNote: SIP is published on 127.0.0.1 only, so only a client on THIS machine can reach it.")
        print(
            "For a phone on your Wi-Fi, set SPARTA_ASTERISK_BIND and SPARTA_ASTERISK_EXTERNAL_IP to this machine's LAN"
        )
        print(f"address (it looks like {lan_address()}) in .env, then: docker compose --profile asterisk up -d")
    print("\nThis is a LOCAL SIP call. Ordinary mobile or landline numbers cannot reach Sparta this way.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="generate the development secrets")
    init.add_argument(
        "--speech", choices=("local", "fake", "azure"), default="local", help="speech providers (default: local)"
    )
    init.add_argument("--force", action="store_true", help="replace existing secrets with new ones")
    init.set_defaults(func=cmd_init)
    show = sub.add_parser("show", help="how to register a SIP client")
    show.add_argument("--reveal", action="store_true", help="print the SIP passwords (they are hidden by default)")
    show.set_defaults(func=cmd_show)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
