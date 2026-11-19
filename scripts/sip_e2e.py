#!/usr/bin/env python3
"""Run the local-SIP end-to-end test: a real Asterisk, real SIP/RTP/G.711 and a headless baresip caller, all in Docker.

    python scripts/sip_e2e.py                      # build + run every scenario (about 10 minutes the first time: Asterisk is compiled)
    python scripts/sip_e2e.py -k scam              # only the scenarios whose name matches
    python scripts/sip_e2e.py --evidence out.json  # also write the measurements (each labelled with how it was measured)
    python scripts/sip_e2e.py --keep-logs logs.txt # keep the containers' output (it contains no secrets; the test checks)

    # The same real SIP call, but with REAL speech: Piper speaks the caller's lines, faster-whisper recognises them inside the
    # API container, Piper speaks the reply. Needs the models (python -m sparta models fetch --dir D) and, in the interpreter
    # that runs the tests, the local-speech extra (pip install -e "services/api[dev,local-speech]"):
    python scripts/sip_e2e.py --speech local --models D [--python PATH_TO_THAT_PYTHON]

Needs Docker (Compose v2) and the backend's dev environment (services/api/.venv or the current interpreter with the
`sparta-api[dev]` extras). Nothing is left running: the stack is removed at the end, including its volumes.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"


def python_for_tests(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in (API / ".venv" / "Scripts" / "python.exe", API / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", dest="keyword", help="only run scenarios matching this pytest -k expression")
    parser.add_argument("--evidence", help="write the measurements (JSON) to this file")
    parser.add_argument("--keep-logs", help="write the container output to this file")
    parser.add_argument(
        "--speech", choices=("fake", "local"), default="fake", help="test-only tone speech, or real local speech"
    )
    parser.add_argument("--models", help="the models directory for --speech local (SPARTA_LOCAL_MODEL_DIR)")
    parser.add_argument(
        "--python", help="interpreter for the tests (--speech local needs one with the local-speech extra)"
    )
    parser.add_argument(
        "--max-call-seconds",
        type=int,
        help="Asterisk's absolute call limit in the test stack (default 30, or 90 for real speech)",
    )
    args = parser.parse_args()

    if shutil.which("docker") is None:
        print("Docker is not installed or not on PATH.", file=sys.stderr)
        return 2
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:  # noqa: S607
        print("The Docker daemon is not running (start Docker Desktop).", file=sys.stderr)
        return 2
    models = args.models or os.environ.get("SPARTA_LOCAL_MODEL_DIR")
    if args.speech == "local" and not models:
        print("--speech local needs --models DIR (python -m sparta models fetch --dir DIR).", file=sys.stderr)
        return 2

    env = {
        **os.environ,
        "SPARTA_SIP_E2E": "1",
        "PYTHONUTF8": "1",
        "SPARTA_SIP_E2E_SPEECH": args.speech,
        "SPARTA_SIP_E2E_MAX_CALL_S": str(args.max_call_seconds or (90 if args.speech == "local" else 30)),
    }
    if models:
        env["SPARTA_LOCAL_MODEL_DIR"] = str(Path(models).resolve())
    if args.evidence:
        env["SPARTA_WRITE_EVIDENCE"] = str(Path(args.evidence).resolve())
    if args.keep_logs:
        env["SPARTA_SIP_E2E_KEEP_LOGS"] = str(Path(args.keep_logs).resolve())
    command = [
        python_for_tests(args.python or os.environ.get("SPARTA_SPEECH_PYTHON")),
        "-X",
        "utf8",
        "-m",
        "pytest",
        "tests/e2e_sip",
        "-v",
        "-p",
        "no:cacheprovider",
        "--timeout=1800",
    ]
    if args.keyword:
        command += ["-k", args.keyword]
    return subprocess.run(command, cwd=API, env=env, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
