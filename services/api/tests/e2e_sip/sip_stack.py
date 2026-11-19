"""Controller for the Docker SIP end-to-end stack (``infrastructure/asterisk/e2e/docker-compose.yml``).

It starts a real Asterisk, the Sparta API and (per scenario) a headless baresip caller, hands each scenario a WAV to play as
the caller's voice, and collects what the caller heard, the SIP events baresip saw, Asterisk's own view and Sparta's API.
All secrets are random per run and reach Docker through the process environment; the caller's SIP password is also in that
run's scenario file, inside a temporary directory that is deleted at the end. Nothing is stored in the repository.
"""

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sip_wavs import read_wav, write_wav

ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = ROOT / "infrastructure" / "asterisk" / "e2e" / "docker-compose.yml"
SECRETS_GLOB = ("webhook", "sip6001", "sip6002")


def token(length: int = 32) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class ClientRun:
    """What one baresip caller did: the SIP events it saw, the audio it played and what it heard."""

    outcome: str
    events: list[dict[str, Any]]
    heard: bytes  # PCM16 mono of everything the caller received (empty if nothing was recorded)
    heard_rate: int
    played: bytes
    seconds: float
    log: str
    closed_by: str | None = None  # "remote" (Sparta or Asterisk hung up) or "local" (the caller did)
    rtp: dict[str, Any] = field(default_factory=dict)

    def event(self, kind: str) -> dict[str, Any] | None:
        return next((e for e in self.events if e["type"] == kind), None)

    def at(self, kind: str) -> float | None:
        found = self.event(kind)
        return None if found is None else float(found["t"])

    @property
    def play_start_ms(self) -> float:
        """Where the caller's file starts inside ``heard`` (both are on the packet tap's single clock)."""
        return float(self.rtp.get("play_start_s", 0.0)) * 1000.0

    def file_clock_ms(self, heard_ms: float) -> float:
        """A time in ``heard`` expressed on the caller's own file clock (0 = the start of what the caller played)."""
        return heard_ms - self.play_start_ms


class Stack:
    def __init__(
        self,
        *,
        stt: str = "fake",
        tts: str = "fake",
        max_call_seconds: int = 45,
        extras: str = "",
        models_dir: Path | None = None,
    ) -> None:
        self.secrets = {name: token(40 if name == "webhook" else 32) for name in SECRETS_GLOB}
        self.work = Path(tempfile.mkdtemp(prefix="sparta-sip-e2e-"))
        (self.work / "data").mkdir()
        self.models = models_dir or (self.work / "no-models")
        self.models.mkdir(exist_ok=True)
        self.env = {
            **os.environ,
            "E2E_STT": stt,
            "E2E_TTS": tts,
            "E2E_EXTRAS": extras,
            "E2E_LOCAL_SPEECH": "1" if "local" in (stt, tts) else "0",
            "E2E_MAX_CALL_SECONDS": str(max_call_seconds),
            "E2E_WEBHOOK_SECRET": self.secrets["webhook"],
            "E2E_SIP_PASSWORD_6001": self.secrets["sip6001"],
            "E2E_SIP_PASSWORD_6002": self.secrets["sip6002"],
            "E2E_DATA_DIR": (self.work / "data").as_posix(),
            "E2E_MODELS_DIR": self.models.as_posix(),
        }
        self.api_base = ""
        self.sip_port = 0
        self._counter = 0
        self._before: set[str] = set()

    # --------------------------------------------------------------------------------------- compose
    def compose(
        self, *args: str, check: bool = True, timeout: float = 900, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        command = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "client", *args]
        return subprocess.run(
            command, env=self.env, capture_output=capture, text=True, timeout=timeout, check=check, cwd=ROOT
        )

    def up(self) -> None:
        self.compose("build", "sipclient", timeout=900)  # `run` would reuse a stale client image
        self.compose("up", "-d", "--build", "--wait", "--wait-timeout", "600", "api", "asterisk", timeout=1500)
        self.api_base = "http://" + self._published("api", "8000")
        self.sip_port = int(self._published("asterisk", "5060", "udp").rsplit(":", 1)[1])

    def _published(self, service: str, port: str, protocol: str = "tcp") -> str:
        out = self.compose("port", "--protocol", protocol, service, port).stdout.strip().splitlines()[0]
        host, _, number = out.rpartition(":")
        return f"{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{number}"

    def down(self) -> None:
        try:
            self.compose("down", "-v", "--remove-orphans", check=False, timeout=300)
        finally:
            shutil.rmtree(self.work, ignore_errors=True)

    # ---------------------------------------------------------------------------------------- views
    def asterisk(self, command: str) -> str:
        done = self.compose(
            "exec", "-T", "asterisk", "asterisk", "-C", "/etc/asterisk/asterisk.conf", "-rx", command, check=False
        )
        return done.stdout + done.stderr

    def logs(self) -> str:
        done = self.compose("logs", "--no-color", "--no-log-prefix", "api", "asterisk", check=False)
        return done.stdout + done.stderr

    def api(self) -> httpx.Client:
        return httpx.Client(base_url=self.api_base + "/api/v1", timeout=15)

    def calls(self) -> list[dict[str, Any]]:
        """The calls created since ``new_test()``: the API cannot delete a call record, so earlier tests' calls are skipped."""
        with self.api() as client:
            items = list(client.get("/calls").json()["items"])
        return [item for item in items if item["id"] not in self._before]

    def new_test(self) -> None:
        """Start of a test: no call of an earlier test may still be on the line, and the calls that exist now are not this test's."""
        self.wait_idle()
        with self.api() as client:
            self._before = {item["id"] for item in client.get("/calls").json()["items"]}

    def detail(self, call_id: str) -> dict[str, Any]:
        with self.api() as client:
            return dict(client.get(f"/calls/{call_id}").json())

    def wait_calls(self, count: int, timeout_s: float = 20) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            items = self.calls()
            if len(items) >= count:
                return items
            time.sleep(0.25)
        raise AssertionError(f"expected {count} call(s), saw {len(self.calls())}")

    def wait_ended(self, call_id: str, timeout_s: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            detail = self.detail(call_id)
            if detail["status"] != "active":
                return detail
            time.sleep(0.25)
        raise AssertionError(f"call {call_id} did not end")

    def clear_calls(self) -> None:
        """Remove the transcripts of every call (the call records themselves stay)."""
        with self.api() as client:
            client.delete("/calls")

    def wait_idle(self, timeout_s: float = 20) -> None:
        """No call left in Asterisk (it hangs up a moment after Sparta does)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if "0 active channels" in self.asterisk("core show channels count"):
                return
            time.sleep(0.5)
        raise AssertionError("Asterisk still has an active channel")

    # ------------------------------------------------------------------------------------- scenarios
    def run_client(
        self,
        *,
        play: bytes | None = None,
        dial: str = "sip:6000@asterisk",
        user: str = "6001",
        password: str | None = None,
        register_only: bool = False,
        max_seconds: float = 60,
        hold_registered_s: float = 3,
        hangup_after_file_s: float = 1.0,
        verbose: bool = False,
    ) -> ClientRun:
        """One baresip caller on the compose network. Its microphone is ``play`` (PCM16 mono, 8 kHz)."""
        self._counter += 1
        folder = self.work / "data" / f"run{self._counter}"
        folder.mkdir()
        scenario = {
            "user": user,
            "password": password if password is not None else self.secrets["sip6001"],
            "domain": "asterisk",
            "dial": dial,
            "play": f"/data/run{self._counter}/in.wav",
            "record": f"/data/run{self._counter}/out.wav",
            "result": f"/data/run{self._counter}/result.json",
            "log": f"/data/run{self._counter}/baresip.log",
            "register_only": register_only,
            "max_seconds": max_seconds,
            "hold_registered_s": hold_registered_s,
            "hangup_after_file_s": hangup_after_file_s,
            "verbose": verbose,
        }
        write_wav(folder / "in.wav", play if play is not None else bytes(16000))
        (folder / "scenario.json").write_text(json.dumps(scenario))
        started = time.monotonic()
        self.compose(
            "run",
            "--rm",
            "-T",
            "sipclient",
            f"/data/run{self._counter}/scenario.json",
            check=False,
            timeout=max_seconds + 120,
        )
        seconds = time.monotonic() - started
        result = json.loads((folder / "result.json").read_text()) if (folder / "result.json").exists() else {}
        out = folder / "out.wav"
        heard, rate = read_wav(out) if out.exists() and out.stat().st_size > 44 else (b"", 8000)
        log_path = folder / "baresip.log"
        return ClientRun(
            outcome=result.get("outcome", "no_result"),
            events=result.get("events", []),
            heard=heard,
            heard_rate=rate,
            played=play or b"",
            seconds=seconds,
            log=log_path.read_text(errors="replace") if log_path.exists() else "",
            closed_by=result.get("closed_by"),
            rtp=result.get("rtp", {}),
        )

    def exec_in_client(self, python_code: str) -> subprocess.CompletedProcess[str]:
        """Run a Python snippet inside a throwaway container on the compose network (an 'unexpected host')."""
        return self.compose(
            "run", "--rm", "-T", "--entrypoint", "python3", "sipclient", "-c", python_code, check=False, timeout=120
        )
