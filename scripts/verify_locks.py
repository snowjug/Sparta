#!/usr/bin/env python3
"""Check that every sha256 in the dependency lock files is a file digest that pypi.org publishes for that release.

The locks are generated through whichever package index the developer has configured, often a corporate mirror. This asks
the public PyPI JSON API for the digests of each pinned release and fails when a lock lists a hash PyPI does not know: the
mirror (or a hand edit) then put a file into the lock that is not the published one. It does not prove a release is free
of vulnerabilities (pip-audit does that) and it checks hashes only for what PyPI serves; a pin that PyPI does not know at
all is reported too. Standard library only.

Exit status: 0 every hash is published on PyPI; 1 at least one hash (or pinned release) is not; 2 PyPI could not be reached,
so nothing was proven.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "services" / "api"
DEFAULT_LOCKS = ("requirements.lock", "requirements-extras.lock", "requirements-build.lock", "requirements-dev.lock")

PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)")
SHA256 = re.compile(r"--hash=sha256:([0-9a-f]{64})")
USER_AGENT = "sparta-verify-locks (+https://github.com/snowjug/Sparta)"

Pin = tuple[str, str]


class LookupFailed(Exception):
    """PyPI could not be queried (network, rate limit or server error): says nothing about the hashes."""


def read_lock(path: Path) -> dict[Pin, set[str]]:
    pins: dict[Pin, set[str]] = {}
    current: Pin | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line)
        if match:
            current = (match.group(1), match.group(2))
            pins.setdefault(current, set())
        if current is not None:
            pins[current].update(SHA256.findall(line))
    return pins


def published_digests(pin: Pin, base_url: str, attempts: int = 4) -> set[str] | None:
    """sha256 digests of every file PyPI lists for the release, or None when the release does not exist."""
    name, version = pin
    request = urllib.request.Request(f"{base_url}/pypi/{name}/{version}/json", headers={"User-Agent": USER_AGENT})
    reason = "unknown error"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            return {item["digests"]["sha256"] for item in data["urls"]}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            reason = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            reason = type(error).__name__
        time.sleep(1.5 * (attempt + 1))
    raise LookupFailed(reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("locks", nargs="*", type=Path, help="lock files (default: the four under services/api)")
    parser.add_argument("--base-url", default="https://pypi.org", help="PyPI-compatible JSON API root (default: %(default)s)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not args.base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        parser.error("--base-url must be an https:// URL (plain http is accepted for localhost only)")
    paths = args.locks or [API_DIR / name for name in DEFAULT_LOCKS]
    per_lock: dict[Path, dict[Pin, set[str]]] = {}
    for path in paths:
        if not path.is_file():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 1
        per_lock[path] = read_lock(path)

    pins = sorted({pin for locked in per_lock.values() for pin in locked})
    print(f"Looking up {len(pins)} pinned release(s) on {args.base_url} ...")

    published: dict[Pin, set[str] | None] = {}
    failed: dict[Pin, str] = {}

    def look_up(pin: Pin) -> None:
        try:
            published[pin] = published_digests(pin, args.base_url.rstrip("/"))
        except LookupFailed as error:
            failed[pin] = str(error)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(look_up, pins))

    unknown = False
    for path, locked in per_lock.items():
        hashes = sum(len(values) for values in locked.values())
        problems: list[str] = []
        for pin, values in sorted(locked.items()):
            if pin in failed:
                continue
            digests = published.get(pin)
            if digests is None:
                problems.append(f"{pin[0]}=={pin[1]}: this release is not on PyPI")
            elif not values:
                problems.append(f"{pin[0]}=={pin[1]}: no sha256 hash in the lock")
            else:
                missing = sorted(values - digests)
                if missing:
                    problems.append(f"{pin[0]}=={pin[1]}: {len(missing)} hash(es) PyPI does not publish for this release, e.g. {missing[0][:16]}...")
        skipped = sum(1 for pin in locked if pin in failed)
        if problems:
            unknown = True
            print(f"[FAIL] {path.name}: {len(problems)} problem(s)")
            for problem in problems:
                print(f"         {problem}")
        elif skipped:
            print(f"[??]   {path.name}: {skipped} of {len(locked)} pin(s) could not be looked up; the rest match")
        else:
            print(f"[ok]   {path.name}: {len(locked)} pins, {hashes} sha256 values, all published on PyPI")

    if unknown:
        return 1
    if failed:
        sample = ", ".join(f"{name}=={version} ({reason})" for (name, version), reason in sorted(failed.items())[:3])
        print(f"error: could not reach PyPI for {len(failed)} pin(s), nothing was proven for them: {sample}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
