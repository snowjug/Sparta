#!/usr/bin/env python3
"""Walk a running Sparta API through the screening journey and check what comes back.

    python scripts/journey.py [--base-url http://127.0.0.1:8000] [--user journey-owner]

Needs the development identity and the simulator (the defaults of `python -m sparta serve`). Standard library only.

Checks, using the simulator (nothing is a real call):
  A. deterministic replays of five curated scenarios (English, Hinglish, Kanglish, a language switch, a legitimate
     delivery): scams are flagged and ended, the legitimate caller is not blocked, the AI disclosure comes first, and
     the replay checksum is identical on a second run.
  B. live calls: the same OTP scam typed in English, Hinglish and Kanglish through the REST API the web app uses.
  C. owner actions on one of them: block, sanitised report, export without the raw number, delete content (the summary
     and transcript go, the risk level stays), and a blocked number is ended automatically next time.

Exit status 0 when every check passes, 1 otherwise. It prints transcripts of the simulated calls, nothing else.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

PROTECTED_ASK = re.compile(
    r"(please|kindly|can you|could you|tell me|share|read out|bataiye|heli)\W+.{0,40}\b(otp|pin|cvv|password)\b",
    re.IGNORECASE,
)
SCAM_TURNS = {
    "English": [
        "Hello, this is Rahul from State Bank of India. Your account has been flagged.",
        "Sir your KYC is pending. To keep your account active tell me the OTP sent to your phone right now.",
    ],
    "Hinglish": [
        "Namaste sir, main SBI bank se bol raha hoon, aapka KYC pending hai.",
        "Account block ho jayega, abhi OTP bataiye jo aapke phone par aaya hai.",
    ],
    "Kanglish": [
        "Namaskara sir, nanu bank inda maatadtidini, nimma KYC pending ide.",
        "Account block aagutte, eega OTP heli, nimma phone ge bandide.",
    ],
}
REPLAYS = (
    ("bank-otp-en", "high"),
    ("kyc-hinglish", "high"),
    ("courier-kanglish", "high"),
    ("language-switch-journey", "high"),
    ("delivery-legit", "not-high"),
)


class Api:
    def __init__(self, base: str, user: str) -> None:
        self.base, self.user = base.rstrip("/") + "/api/v1", user

    def call(self, method: str, path: str, body: object | None = None) -> tuple[int, dict | list | str, dict]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("X-Sparta-Dev-User", self.user)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw, status = response.read().decode("utf-8"), response.status
                headers = {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as error:
            raw, status = error.read().decode("utf-8"), error.code
            headers = {k.lower(): v for k, v in error.headers.items()}
        try:
            return status, json.loads(raw) if raw else "", headers
        except json.JSONDecodeError:
            return status, raw, headers


def show(label: str, call: dict, problems: list[str]) -> None:
    print(f"\n=== {label}")
    print(
        f"status={call['status']} profile={call['language_profile']} langs={call['languages']} "
        f"risk={call['risk_level']}({call['risk_score']}) category={call['category']} action={call['action_taken']}"
    )
    for turn in call["turns"]:
        speaker = "A" if turn["speaker"] == "assistant" else "C"
        print(f"  {speaker} [{turn['language']}] {turn['text']}"[:220])
        if turn["speaker"] == "assistant" and PROTECTED_ASK.search(turn.get("translation") or turn["text"]):
            problems.append(f"{label}: the assistant may be asking for protected information: {turn['text'][:80]}")
    first = next((t for t in call["turns"] if t["speaker"] == "assistant"), None)
    if first is None or not re.search(r"\bAI\b", first["text"]):
        problems.append(f"{label}: the first assistant line does not disclose that it is an AI")
    print("  summary:", ((call.get("summary") or {}).get("text") or "")[:260])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="journey-owner")
    args = parser.parse_args()
    api, problems = Api(args.base_url, args.user), []

    status, info, _ = api.call("GET", "/system/status")
    if status != 200 or not isinstance(info, dict):
        print(f"cannot reach {args.base_url}: HTTP {status}. Start the API: python -m sparta serve", file=sys.stderr)
        return 1
    print(f"Sparta {info['version']} ({info['env']}, auth {info['auth_mode']}), telephony: {info['telephony']['note']}")

    print("\n##### A. deterministic replays")
    for scenario, expectation in REPLAYS:
        status, body, _ = api.call("POST", "/simulator/replay", {"scenario_id": scenario})
        if status != 200:
            problems.append(f"{scenario}: HTTP {status}")
            continue
        call = body["call"]
        show(f"replay {scenario}", call, problems)
        high = call["risk_level"] == "high"
        if (expectation == "high") != high:
            problems.append(f"{scenario}: expected risk {expectation}, got {call['risk_level']}")
        if expectation == "not-high" and call["action_taken"] in ("refused_and_ended", "ended_high_risk_call"):
            problems.append(f"{scenario}: a legitimate caller was ended")
        again = api.call("POST", "/simulator/replay", {"scenario_id": scenario})[1]
        if again["checksum"] != body["checksum"]:
            problems.append(f"{scenario}: the replay is not deterministic")

    print("\n##### B. live calls typed through the REST API")
    numbers: dict[str, str] = {}
    call_ids: dict[str, str] = {}
    for name, turns in SCAM_TURNS.items():
        numbers[name] = "+9198" + str(time.time_ns())[-8:]
        status, created, _ = api.call(
            "POST",
            "/simulator/calls",
            {"caller_number": numbers[name], "caller_label": f"{name} scam test", "silence_timers": "off"},
        )
        if status != 201:
            problems.append(f"live {name}: could not start a call (HTTP {status})")
            continue
        call_ids[name] = created["id"]
        for text in turns:
            status, _, _ = api.call("POST", f"/calls/{created['id']}/turns", {"text": text, "source": "typed"})
            if status != 200:
                problems.append(f"live {name}: a turn was refused (HTTP {status})")
        detail = api.call("GET", f"/calls/{created['id']}")[1]
        for _ in range(40):  # the farewell has to finish playing before the call is closed
            if detail["status"] == "ended":
                break
            time.sleep(1)
            detail = api.call("GET", f"/calls/{created['id']}")[1]
        show(f"live {name}", detail, problems)
        if detail["risk_level"] != "high" or detail["status"] != "ended":
            problems.append(
                f"live {name}: expected a high-risk call that ended, got {detail['risk_level']}/{detail['status']}"
            )

    if "English" in call_ids:
        print("\n##### C. owner actions and privacy")
        cid, raw = call_ids["English"], numbers["English"][3:]
        print("block:", api.call("POST", f"/calls/{cid}/block", {})[0])
        status, report, headers = api.call("GET", f"/calls/{cid}/report")
        print("report:", status, headers.get("content-disposition"))
        if raw in json.dumps(report) or "OTP sent to your phone" in json.dumps(report):
            problems.append("the sanitised report contains the raw number or transcript text")
        status, export, _ = api.call("GET", f"/calls/{cid}/export")
        print("export:", status, "| raw number in export:", raw in json.dumps(export))
        if raw in json.dumps(export):
            problems.append("the export contains the raw number")
        print("delete content:", api.call("DELETE", f"/calls/{cid}/content")[0])
        after = api.call("GET", f"/calls/{cid}")[1]
        print(f"after: turns={len(after['turns'])} has_content={after['has_content']} risk_level={after['risk_level']}")
        if after["turns"] or after["has_content"] or after["risk_level"] != "high":
            problems.append("deleting the content must remove the transcript but keep the risk level")
        status, again, _ = api.call(
            "POST", "/simulator/calls", {"caller_number": numbers["English"], "silence_timers": "off"}
        )
        print("same number again:", status, again.get("action_taken") if isinstance(again, dict) else again)
        if status != 201 or again.get("action_taken") != "ended_blocked_number":
            problems.append("a blocked number was not ended automatically")

    print("\nPROBLEMS:", json.dumps(problems, indent=1, ensure_ascii=False) if problems else "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
