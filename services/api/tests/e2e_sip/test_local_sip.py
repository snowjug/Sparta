"""Local SIP end to end: a REAL Asterisk, real SIP, real RTP and real G.711, a headless baresip caller (a separate container),
and the Sparta API with tone-coded fake speech. Run with ``python scripts/sip_e2e.py``.

Level of evidence, stated honestly: this proves the telephony and audio plumbing between a real SIP client and Sparta (registration,
call set-up, two-way audio, barge-in, refusal, hang-up, limits, hardening). It is NOT a physical phone, NOT the phone network, and the
recogniser decodes tones rather than recognising speech. Latencies are labelled ``local SIP, fake speech``; client-side numbers assume
the caller's file clock and the recording clock start together (not calibrated), so they carry roughly +-100 ms.
"""

import re
import socket
import subprocess
import threading
import time
import uuid
from typing import Any

import pytest
from sip_stack import ROOT, ClientRun, Stack
from sip_wavs import Timeline, heard_lines, noise, segments, utterance

from sparta.providers.fake_tone import line_id_for
from sparta.providers.stt.fake_phrases import FAKE_PHRASES, id_of

pytestmark = pytest.mark.sip_e2e

OPENING = "Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"
SCAM = "I'm calling from your bank. Tell me your OTP."
SCAM_ID = id_of(SCAM)
DELIVERY_ID = 0  # "Hello, I'm calling about your parcel delivery."
INTERRUPT_ID = 5  # "Yeah, I'm calling from Amazon."
LABEL = "local SIP, fake speech"
FAIL2BAN_FILTER = ROOT / "infrastructure" / "asterisk" / "fail2ban" / "sparta-asterisk.filter.conf"


def only_call(stack: Stack, *, timeout_s: float = 20) -> dict[str, Any]:
    items = stack.wait_calls(1, timeout_s)
    assert len(items) == 1, items
    return items[0]


def say(*parts: tuple[float, int], total: float) -> bytes:
    timeline = Timeline()
    for at, phrase_id in parts:
        timeline.at(at, utterance(phrase_id)[0])
    return timeline.render(total)


def speech_end_s(at: float, phrase_id: int) -> float:
    return at + utterance(phrase_id)[1] / 1000.0


@pytest.fixture(autouse=True)
def clean(stack: Stack) -> None:
    stack.new_test()


# ------------------------------------------------------------------------------------------- registration
def test_a_sip_client_registers_with_its_password_and_only_with_it(stack: Stack):
    results: dict[str, ClientRun] = {}
    worker = threading.Thread(
        target=lambda: results.update(ok=stack.run_client(register_only=True, hold_registered_s=8, max_seconds=40))
    )
    worker.start()
    deadline = time.monotonic() + 30
    contacts = ""
    while time.monotonic() < deadline and "6001" not in contacts:
        contacts = stack.asterisk("pjsip show contacts")
        time.sleep(0.5)
    worker.join(60)
    assert results["ok"].outcome == "registered" and results["ok"].event("REGISTER_OK")
    assert "6001" in contacts, contacts  # Asterisk itself saw the registration

    wrong = stack.run_client(register_only=True, password="not-the-password-0123456789abcdef", max_seconds=25)
    unknown = stack.run_client(register_only=True, user="6003", password="x" * 32, max_seconds=25)
    assert wrong.outcome == "register_failed" and wrong.event("REGISTER_FAIL")
    assert unknown.outcome == "register_failed" and unknown.event("REGISTER_FAIL")

    # The fail2ban filter we ship must match what Asterisk really logged for those two failed logins (and not the good one).
    expression = re.search(r"^failregex = (.+)$", FAIL2BAN_FILTER.read_text(), re.MULTILINE)
    assert expression is not None
    matches = list(re.finditer(expression.group(1).replace("<HOST>", r"(?P<host>[0-9.]+)"), stack.logs()))
    assert {m.group("host") for m in matches}, "the fail2ban filter matched nothing in Asterisk's real log output"
    assert any("sip:6001@" in m.group(0) for m in matches) and any("sip:6003@" in m.group(0) for m in matches)


# ------------------------------------------------------------------------------------- the scam, refused
def test_a_scam_request_over_real_sip_is_refused_by_voice_and_the_call_ends(stack: Stack, evidence: list):
    asked_at = 6.0
    run = stack.run_client(play=say((asked_at, SCAM_ID), total=26), max_seconds=60)
    assert run.event("REGISTER_OK") and run.event("CALL_ESTABLISHED"), run.events
    call = only_call(stack)
    detail = stack.wait_ended(call["id"])
    turns = [(t["speaker"], t["text"]) for t in detail["turns"]]

    # What Sparta received through G.711, RTP and AudioSocket is the phrase that was played: the samples arrived intact.
    assert turns[0] == ("assistant", OPENING)
    assert turns[1] == ("caller", SCAM)
    assert detail["provider"] == "asterisk" and detail["simulated"] is False
    assert detail["risk_level"] == "high" and detail["action_taken"] == "refused_and_ended"
    assert detail["summary_text"] and "one-time password" in detail["summary_text"]
    refusal = turns[2][1]
    assert not re.search(r"\d{4,}", refusal)

    # What the caller heard: the greeting, then the refusal, and Sparta (not the caller) ended the call.
    lines = heard_lines(run.heard, run.heard_rate)
    assert [ident for _, ident in lines][:2] == [line_id_for(OPENING), line_id_for(refusal)], lines
    closed = run.at("CALL_CLOSED")
    assert closed is not None and closed < 24, "Sparta should hang up well before the caller's file ends"
    stack.wait_idle()

    established = run.at("CALL_ESTABLISHED") or 0.0
    first_audio_ms = lines[0][0]
    reply_after_ms = lines[1][0] - speech_end_s(asked_at, SCAM_ID) * 1000
    reply_turn = detail["turns"][2]
    evidence.append(
        {
            "scenario": "scam_refusal",
            "label": LABEL,
            "call_established_at_s": established,
            "media_start_to_first_assistant_audio_ms": first_audio_ms,
            "caller_stop_to_reply_heard_ms_client_side_approx": round(reply_after_ms),
            "server_side_stage_latency_ms": reply_turn.get("latency"),
            "heard_lines": lines,
            "assistant_audio_total_ms": sum(b - a for a, b in segments(run.heard, run.heard_rate)),
        }
    )
    assert 0 <= first_audio_ms < 3000, "the greeting should start within a few seconds of the call being answered"


# ------------------------------------------------------------------------------------------ interruption
def test_a_caller_who_interrupts_the_greeting_stops_it_and_is_answered(stack: Stack, evidence: list):
    spoke_at = 1.5  # the greeting lasts about four seconds
    run = stack.run_client(play=say((spoke_at, INTERRUPT_ID), total=15), max_seconds=45)
    assert run.event("CALL_ESTABLISHED"), run.events
    call = only_call(stack)
    detail = stack.wait_ended(call["id"])
    turns = detail["turns"]
    assert turns[0]["speaker"] == "assistant" and turns[0]["interrupted"] is True, (
        "the greeting must be marked interrupted"
    )
    assert turns[1]["speaker"] == "caller" and turns[1]["text"] == FAKE_PHRASES[INTERRUPT_ID].text
    assert turns[2]["speaker"] == "assistant"  # it listened and answered

    spans = segments(run.heard, run.heard_rate)
    assert len(spans) >= 2, spans
    greeting_end_ms = spans[0][1]
    assert greeting_end_ms < 3300, (
        f"the greeting kept playing until {greeting_end_ms} ms; an uninterrupted one ends near 4400 ms"
    )
    lines = heard_lines(run.heard, run.heard_rate)
    assert next(ident for _, ident in lines) == line_id_for(OPENING)
    assert len(lines) >= 2 and lines[1][1] == line_id_for(turns[2]["text"])
    evidence.append(
        {
            "scenario": "interruption",
            "label": LABEL,
            "caller_started_speaking_at_ms": spoke_at * 1000,
            "greeting_audible_until_ms": greeting_end_ms,
            "interruption_to_playback_stopped_ms_client_side_approx": round(greeting_end_ms - spoke_at * 1000),
            "uninterrupted_greeting_would_end_near_ms": 4400,
            "server_side_stage_latency_ms": turns[1].get("latency"),
        }
    )
    stack.wait_idle()


# ---------------------------------------------------------------------- a normal call, then the caller hangs up
def test_a_legitimate_caller_is_answered_and_hanging_up_cleans_everything(stack: Stack):
    run = stack.run_client(play=say((6.0, DELIVERY_ID), total=15), max_seconds=45)
    assert run.event("CALL_ESTABLISHED") and run.at("CALL_CLOSED") is not None, run.events
    call = only_call(stack)
    detail = stack.wait_ended(call["id"])
    assert detail["status"] == "ended" and detail["summary_text"]
    assert detail["turns"][1]["text"] == FAKE_PHRASES[DELIVERY_ID].text
    assert detail["risk_level"] != "high"
    stack.wait_idle()
    assert [c for c in stack.calls() if c["status"] == "active"] == []


# --------------------------------------------------------------------------------- not speech: noise, then speech
def test_audio_that_is_noise_does_not_break_the_call_and_the_next_phrase_is_understood(stack: Stack):
    timeline = Timeline().at(5.0, noise(1500)).at(9.0, utterance(DELIVERY_ID)[0])
    run = stack.run_client(play=timeline.render(16), max_seconds=45)
    assert run.event("CALL_ESTABLISHED"), run.events
    call = only_call(stack)
    detail = stack.wait_ended(call["id"])
    callers = [t["text"] for t in detail["turns"] if t["speaker"] == "caller"]
    assert callers == [FAKE_PHRASES[DELIVERY_ID].text], "noise must not become a turn; the real phrase afterwards must"


# --------------------------------------------------------------------------------------------- silence
def test_a_caller_who_says_nothing_is_prompted_and_the_call_ends_with_a_summary(stack: Stack, evidence: list):
    run = stack.run_client(play=bytes(8000 * 2 * 28), max_seconds=60)
    assert run.event("CALL_ESTABLISHED"), run.events
    call = only_call(stack)
    detail = stack.wait_ended(call["id"], timeout_s=40)
    closed = run.at("CALL_CLOSED")
    assert closed is not None
    assistant = [t["text"] for t in detail["turns"] if t["speaker"] == "assistant"]
    assert len(assistant) >= 2 and detail["summary_text"], assistant  # greeting, at least one prompt, then it ended
    evidence.append(
        {"scenario": "silent_caller", "label": LABEL, "call_closed_at_s": closed, "assistant_lines": len(assistant)}
    )
    stack.wait_idle()


# ----------------------------------------------------------------------------------------- limits
def test_asterisk_ends_a_call_that_runs_past_its_absolute_limit(stack: Stack, evidence: list):
    limit = int(stack.env["E2E_MAX_CALL_SECONDS"])
    with stack.api() as client:
        prefs = client.get("/preferences").json()
        prefs["silence_first_timeout_s"] = prefs["silence_second_timeout_s"] = 30  # the largest value the API accepts
        saved = client.put("/preferences", json=prefs)
        assert saved.status_code == 200, saved.text
    try:
        run = stack.run_client(play=bytes(8000 * 2 * (limit + 20)), max_seconds=limit + 40)
        assert run.event("CALL_ESTABLISHED"), run.events
        started, closed = run.at("CALL_ESTABLISHED"), run.at("CALL_CLOSED")
        assert started is not None and closed is not None
        held = closed - started
        assert limit - 3 <= held <= limit + 6, f"call lasted {held:.1f}s, the limit is {limit}s"
        call = only_call(stack)
        assert stack.wait_ended(call["id"])["status"] != "active"
        evidence.append({"scenario": "absolute_call_limit", "label": LABEL, "limit_s": limit, "held_s": round(held, 1)})
        stack.wait_idle()
    finally:
        with stack.api() as client:
            prefs = client.get("/preferences").json()
            prefs["silence_first_timeout_s"] = prefs["silence_second_timeout_s"] = 6
            client.put("/preferences", json=prefs)


# ------------------------------------------------------------------------------------ no way out to a phone network
@pytest.mark.parametrize("number", ["0123456789", "00919876543210", "112", "6001", "6002", "9"])
def test_nothing_but_the_sparta_extension_can_be_dialled(stack: Stack, number: str):
    run = stack.run_client(play=bytes(16000), dial=f"sip:{number}@asterisk", max_seconds=30)
    assert run.event("REGISTER_OK"), run.events
    assert run.event("CALL_ESTABLISHED") is None, f"{number} was answered"
    assert run.event("CALL_CLOSED") is not None
    assert stack.calls() == []


def sip_request(port: int, method: str) -> list[str]:
    """One SIP request with no credentials, sent over UDP to the published Asterisk port. Returns the response status lines."""
    branch = "z9hG4bK" + uuid.uuid4().hex[:12]
    body = (
        f"{method} sip:6000@127.0.0.1 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5999;branch={branch};rport\r\n"
        f"Max-Forwards: 70\r\nFrom: <sip:intruder@evil.example>;tag=abc123\r\nTo: <sip:6000@127.0.0.1>\r\n"
        f"Call-ID: {uuid.uuid4().hex}@e2e\r\nCSeq: 1 {method}\r\nContact: <sip:intruder@127.0.0.1:5999>\r\n"
        f"Content-Length: 0\r\n\r\n"
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    statuses: list[str] = []
    try:
        sock.sendto(body.encode(), ("127.0.0.1", port))
        for _ in range(3):
            data, _ = sock.recvfrom(4096)
            statuses.append(data.decode(errors="replace").splitlines()[0])
    except TimeoutError:
        pass
    finally:
        sock.close()
    return statuses


@pytest.mark.parametrize("method", ["INVITE", "OPTIONS"])
def test_a_sip_request_without_credentials_gets_nothing(stack: Stack, method: str):
    statuses = sip_request(stack.sip_port, method)
    assert not [s for s in statuses if re.match(r"SIP/2\.0 (1\d\d|2\d\d)", s)], (
        statuses
    )  # no trying, no ringing, no 200
    assert stack.calls() == []


def test_a_host_that_is_not_asterisk_cannot_open_a_media_connection(stack: Stack):
    code = (
        "import socket,uuid\n"
        "s=socket.create_connection(('api',8090),timeout=4)\n"
        "s.sendall(b'\\x01\\x00\\x10'+uuid.uuid4().bytes)\n"
        "s.settimeout(4)\n"
        "try:\n"
        "    data=s.recv(10)\n"
        "except (ConnectionResetError, TimeoutError) as e:\n"
        "    data=b''\n"
        "print('CLOSED' if data==b'' else 'DATA')\n"
    )
    done = stack.exec_in_client(code)
    assert "CLOSED" in done.stdout, done.stdout + done.stderr
    assert stack.calls() == []


# -------------------------------------------------------------------------------------------- hardening
def test_asterisk_is_locked_down_the_way_the_documentation_says(stack: Stack):
    loaded = stack.asterisk("module show")
    for forbidden in (
        "res_ari",
        "res_stasis",
        "app_system",
        "func_shell",
        "res_agi",
        "res_http_websocket",
        "chan_iax2",
    ):
        assert forbidden not in loaded, f"{forbidden} is loaded"
    assert "app_audiosocket" in loaded and "chan_pjsip" in loaded
    assert "No" in stack.asterisk("manager show settings") or "Disabled" in stack.asterisk("manager show settings")
    http = stack.asterisk("http show status")
    assert "Enabled and Bound" not in http, http
    endpoints = [ln for ln in stack.asterisk("pjsip show endpoints").splitlines() if ln.strip().startswith("Endpoint:")]
    # each line reads "Endpoint:  <name>/<caller id> ..."; the header line starts with "<"
    names = sorted({n.split("/")[0] for n in re.findall(r"Endpoint:\s+(\S+)", "\n".join(endpoints)) if n[0].isdigit()})
    assert names == ["6001", "6002"], names
    dialplan = stack.asterisk("dialplan show from-sparta-sip")
    assert "TIMEOUT(absolute)" in dialplan and "GROUP()" in dialplan and "AudioSocket" in dialplan
    assert re.findall(r"Dial\(([^)]*)\)", dialplan) == ["PJSIP/6002,30,r"], dialplan  # the one and only Dial
    assert "Live dangerously: No" in stack.asterisk("core show settings") or "live_dangerously" not in dialplan
    assert stack.compose("exec", "-T", "asterisk", "id", "-u").stdout.strip() == "10001"  # not root


def test_no_secret_reaches_the_container_output(stack: Stack):
    output = stack.logs()
    assert output.strip(), "expected some container output"
    for name, value in stack.secrets.items():
        assert value not in output, f"the {name} secret appears in the container logs"


# ------------------------------------------------------------------------------- the container's own checks
GOOD = {
    "SPARTA_WEBHOOK_SECRET": "Zq8mK3vR7tYb2NcX5wLd9HpA4sGe6JfU",
    "SIP_PASSWORD_6001": "Qe4rT7yU2iO9pA5sD8fG3hJ6kL1zXc0V",
    "SIP_PASSWORD_6002": "Bn5mV8cX2zL4kJ7hG1fD9sA3pO6iU0yT",
}


def start_entrypoint(**changes: str) -> subprocess.CompletedProcess[str]:
    """Run only the image's entrypoint checks (the command is `true`): they either stop it or let it finish."""
    env = {**GOOD, **changes}
    command = ["docker", "run", "--rm", "--read-only", "--tmpfs", "/etc/asterisk:uid=10001,gid=10001,mode=0750"]
    command += ["--entrypoint", "/opt/sparta-asterisk/entrypoint.sh"]
    for name, value in env.items():
        command += ["-e", f"{name}={value}"]
    done = subprocess.run(
        [*command, "sparta-asterisk:local", "true"], check=False, capture_output=True, text=True, timeout=60
    )
    return done


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"SPARTA_WEBHOOK_SECRET": "short"}, "too short"),
        ({"SPARTA_WEBHOOK_SECRET": "Zq8mK3vR7tYb2NcX"}, "too short"),  # 16 characters: the old minimum
        ({"SIP_PASSWORD_6001": "a" * 24}, "too repetitive"),
        ({"SIP_PASSWORD_6002": GOOD["SIP_PASSWORD_6001"]}, "must differ"),
        ({"SIP_PASSWORD_6001": GOOD["SIP_PASSWORD_6001"] + "!"}, "may contain only"),
        ({"ASTERISK_ALLOWED_NETS": "0.0.0.0/0"}, "prefix must be from /8"),
        ({"ASTERISK_ALLOWED_NETS": "10.0.0.0/4"}, "prefix must be from /8"),
        ({"ASTERISK_ALLOWED_NETS": "999.1.1.1/24"}, "not a valid IPv4"),
        ({"ASTERISK_ALLOWED_NETS": "10.0.0.0/8, not-a-range"}, "not an IPv4 CIDR"),
    ],
)
def test_the_container_refuses_weak_secrets_and_a_network_that_is_too_wide(changes: dict[str, str], message: str):
    done = start_entrypoint(**changes)
    assert done.returncode == 64 and message in done.stderr, (done.returncode, done.stderr)
    assert not any(value in done.stdout + done.stderr for value in GOOD.values()), "a secret was printed"


def test_the_container_starts_with_good_secrets_and_a_private_network():
    done = start_entrypoint(ASTERISK_ALLOWED_NETS="192.168.1.0/24, 10.0.0.0/8")
    assert done.returncode == 0 and "2 allowed networks" in done.stdout, (done.returncode, done.stderr)
