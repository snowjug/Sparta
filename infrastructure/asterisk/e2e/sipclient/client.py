#!/usr/bin/env python3
"""Headless SIP caller for the Sparta end-to-end test: drives ``baresip`` (a mature open-source SIP user agent) with
nothing but its own, documented interfaces.

Scenario file (JSON), written by the test harness:
    {"user": "6001", "password": "...", "domain": "asterisk", "dial": "sip:6000@asterisk",
     "play": "/data/in.wav",        # the caller's microphone: baresip plays this file into the call (8 kHz mono PCM16)
     "record": "/data/out.wav",     # what the caller HEARS, rebuilt from the RTP that reached this container
     "register_only": false, "max_seconds": 90, "hangup_after_file_s": 1.0}

baresip registers (REGISTER with digest authentication), dials and plays the WAV as the caller's voice; the call is hung up a
moment after the file ends (or earlier by Sparta). Everything is real SIP, real RTP and real G.711.

What the caller hears is recorded from the wire: baresip has no real-time file recorder, and its decoder dump has no timing
(Asterisk sends no RTP while Sparta is silent). A raw packet tap on this container's own network interface keeps each RTP
packet's arrival time, and the recording is rebuilt on one time line: ``result.json`` carries ``play_start_s``, the offset of the
caller's file start inside the recording, so latencies are measured on a single clock. The tap only reads this container's own
traffic, which is why this test-only container runs as root (CAP_NET_RAW); it is never part of the product.
"""

import audioop
import json
import socket
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

CONF = Path("/tmp/baresip-conf")
CTRL_PORT = 4444
RTP_PORTS = (40000, 40100)
RATE = 8000
PACKET_OUTGOING = 4  # sockaddr_ll.sll_pkttype of a packet this host sent
RTP_CODEC = {0: ("PCMU", audioop.ulaw2lin), 8: ("PCMA", audioop.alaw2lin)}


def write_config(scenario: dict, domain_ip: str) -> str:
    """Write baresip's config and return the account line. The account is not written to disk: ``main`` creates it over the
    control socket once connected, so the REGISTER_OK / REGISTER_FAIL event can never fire before anyone is listening."""
    CONF.mkdir(parents=True, exist_ok=True)
    (CONF / "config").write_text(
        "\n".join(
            [
                "call_local_timeout 60",
                "call_max_calls 1",
                "audio_source aufile," + scenario.get("play", "/data/in.wav"),
                "module_path /usr/lib/baresip/modules",
                "module g711.so",
                "module aufile.so",
                "module account.so",
                "module contact.so",
                "module menu.so",
                "module ctrl_tcp.so",
                f"ctrl_tcp_listen 127.0.0.1:{CTRL_PORT}",
                "sip_listen 0.0.0.0:5070",
                f"rtp_ports {RTP_PORTS[0]}-{RTP_PORTS[1]}",
                "audio_buffer 20-160",
            ]
            + (["sip_trace yes"] if scenario.get("verbose") else [])
            + [""]
        )
    )
    # An address, not a name: a phone on a LAN registers to the server's IP, and it skips the SRV/NAPTR lookups
    # (seconds of timeouts behind some resolvers) that a host name would trigger.
    account = (
        f"<sip:{scenario['user']}@{domain_ip}>;auth_pass={scenario['password']};regint=60;transport=udp;"
        "audio_codecs=PCMU/8000/1,PCMA/8000/1;answermode=manual"
    )
    (CONF / "accounts").write_text("")
    (CONF / "contacts").write_text("")
    return account


class Ctrl:
    """baresip's ctrl_tcp interface: netstrings of JSON, ``<length>:<json>,``."""

    def __init__(self) -> None:
        self.sock = socket.create_connection(("127.0.0.1", CTRL_PORT), timeout=5)
        self.sock.settimeout(0.2)
        self.buffer = b""

    def poll(self) -> list[dict]:
        out: list[dict] = []
        try:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("ctrl_tcp closed")
            self.buffer += data
        except TimeoutError:
            pass
        while True:
            head, sep, rest = self.buffer.partition(b":")
            if not sep or not head.isdigit():
                break
            size = int(head)
            if len(rest) < size + 1:
                break
            out.append(json.loads(rest[:size]))
            self.buffer = rest[size + 1 :]
        return out

    def command(self, command: str, params: str = "", token: str = "t") -> None:
        body = json.dumps({"command": command, "params": params, "token": token}).encode()
        self.sock.sendall(str(len(body)).encode() + b":" + body + b",")


class RtpTap(threading.Thread):
    """Reads this container's own RTP straight off the network interface, with the arrival time of every packet."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.inbound: list[tuple[float, int, int, bytes]] = []  # (arrival, rtp timestamp, payload type, payload)
        self.out_first: float | None = None
        self.out_count = 0
        self._halt = threading.Event()
        self._sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))  # ETH_P_ALL
        self._sock.settimeout(0.2)

    def stop(self) -> None:
        self._halt.set()
        self.join(2)
        self._sock.close()

    def run(self) -> None:
        low, high = RTP_PORTS
        while not self._halt.is_set():
            try:
                frame, address = self._sock.recvfrom(2048)
            except TimeoutError:
                continue
            now = time.monotonic()
            if len(frame) < 42 or frame[12:14] != b"\x08\x00" or frame[23] != 17:  # IPv4 + UDP only
                continue
            udp = 14 + (frame[14] & 0x0F) * 4
            src, dst, length = struct.unpack("!HHH", frame[udp : udp + 6])
            packet = frame[udp + 8 : udp + length]
            if len(packet) < 12 or packet[0] >> 6 != 2 or (packet[1] & 0x7F) not in RTP_CODEC:
                continue  # not RTP of a G.711 payload (this also drops RTCP and telephone-event)
            header = 12 + 4 * (packet[0] & 0x0F)
            if packet[0] & 0x10:
                header += 4 + 4 * struct.unpack("!H", packet[header + 2 : header + 4])[0]
            payload = packet[header : len(packet) - (packet[-1] if packet[0] & 0x20 else 0)]
            if address[2] == PACKET_OUTGOING and low <= src <= high:
                self.out_count += 1
                self.out_first = self.out_first if self.out_first is not None else now
            elif address[2] != PACKET_OUTGOING and low <= dst <= high:
                self.inbound.append((now, struct.unpack("!I", packet[4:8])[0], packet[1] & 0x7F, payload))


def rebuild(inbound: list[tuple[float, int, int, bytes]], origin: float) -> bytes:
    """PCM16 of everything received, each packet where it belongs on the time line (silence where nothing arrived).

    A packet is placed by its RTP timestamp, which follows the sender's clock across silences; if the timestamp and the
    arrival time disagree by more than 100 ms (a sender whose clock stood still while it was quiet) the arrival time wins.
    """
    pcm = bytearray()
    anchor_pos = anchor_ts = None
    for arrived, timestamp, payload_type, payload in inbound:
        arrival = round((arrived - origin) * RATE)
        if anchor_pos is None or anchor_ts is None:
            anchor_pos, anchor_ts = arrival, timestamp
        delta = (timestamp - anchor_ts) & 0xFFFFFFFF
        position = anchor_pos + (delta - (1 << 32) if delta >= 1 << 31 else delta)
        if abs(arrival - position) > RATE // 10:
            anchor_pos, anchor_ts, position = arrival, timestamp, arrival
        samples = RTP_CODEC[payload_type][1](payload, 2)
        start = max(0, position) * 2
        if len(pcm) < start + len(samples):
            pcm.extend(bytes(start + len(samples) - len(pcm)))
        pcm[start : start + len(samples)] = samples
    return bytes(pcm)


def wav_seconds(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def save_recording(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)


def main() -> int:
    scenario = json.loads(Path(sys.argv[1]).read_text())
    result_path = Path(scenario.get("result", "/data/result.json"))
    domain_ip = socket.gethostbyname(scenario["domain"])
    account = write_config(scenario, domain_ip)
    target = scenario["dial"].replace("@" + scenario["domain"], "@" + domain_ip)
    file_seconds = wav_seconds(scenario["play"]) if Path(scenario["play"]).exists() else 0.0
    log = open(scenario.get("log", "/data/baresip.log"), "wb")  # noqa: SIM115 - lives as long as the process
    tap = RtpTap()
    tap.start()
    command = ["baresip", "-f", str(CONF)] + (["-v"] if scenario.get("verbose") else [])
    started = time.monotonic()
    # stdbuf keeps baresip's output line-buffered so every log line can carry the time it was printed.
    proc = subprocess.Popen(  # noqa: S603
        ["stdbuf", "-oL", "-eL", *command],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    def pump_log() -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            log.write(f"[{time.monotonic() - started:7.3f}] ".encode() + raw)
            log.flush()

    pump = threading.Thread(target=pump_log, daemon=True)
    pump.start()
    events: list[dict] = []
    outcome = "error"
    closed_by: str | None = None
    ctrl: Ctrl | None = None
    for _ in range(100):
        try:
            ctrl = Ctrl()
            break
        except OSError:
            time.sleep(0.1)
    try:
        if ctrl is None:
            raise RuntimeError("baresip's control port never opened")
        ctrl.command("uanew", account, "uanew")
        registered = dialled = hung_up = False
        established_at: float | None = None
        deadline = started + float(scenario.get("max_seconds", 90))
        outcome = "timeout"
        while time.monotonic() < deadline and outcome == "timeout":
            for message in ctrl.poll():
                if not message.get("event"):
                    continue
                kind = message.get("type")
                now = time.monotonic()
                events.append({"t": round(now - started, 3), "type": kind, "param": message.get("param", "")})
                if kind == "REGISTER_OK":
                    registered = True
                elif kind == "REGISTER_FAIL":
                    outcome = "register_failed"
                elif kind == "CALL_ESTABLISHED":
                    established_at = now
                elif kind == "CALL_CLOSED":
                    outcome = "call_closed"
                    closed_by = "local" if hung_up else "remote"
            now = time.monotonic()
            if registered and scenario.get("register_only") and outcome == "timeout":
                time.sleep(float(scenario.get("hold_registered_s", 3)))
                outcome = "registered"
            elif registered and not dialled and outcome == "timeout":
                ctrl.command("dial", target, "dial")
                dialled = True
            elif established_at is not None and not hung_up:
                if now - established_at >= file_seconds + float(scenario.get("hangup_after_file_s", 1.0)):
                    ctrl.command("hangup", "", "hangup")
                    hung_up = True
        if outcome == "call_closed":
            time.sleep(0.3)  # the last packets of the call
    finally:
        if ctrl is not None:
            try:
                ctrl.command("quit", "", "q")
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        pump.join(2)
        log.close()
        tap.stop()
    rtp: dict = {"in_packets": len(tap.inbound), "out_packets": tap.out_count}
    if tap.inbound:
        play_start = (tap.out_first - 0.02) if tap.out_first is not None else tap.inbound[0][0]
        origin = min(play_start, tap.inbound[0][0])
        save_recording(scenario.get("record", "/data/out.wav"), rebuild(tap.inbound, origin))
        rtp.update(
            codec=RTP_CODEC[tap.inbound[0][2]][0],
            play_start_s=round(play_start - origin, 3),
            first_audio_in_s=round(tap.inbound[0][0] - origin, 3),
            origin_at_s=round(origin - started, 3),
        )
    result_path.write_text(json.dumps({"outcome": outcome, "closed_by": closed_by, "rtp": rtp, "events": events}, indent=1))
    return 0 if outcome in ("call_closed", "registered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
