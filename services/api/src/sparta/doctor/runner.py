"""``sparta doctor``: assemble the preflight report.

Offline checks always run. ``online=True`` adds free network checks, ``allow_billable=True`` (only with ``online``) adds
the few probes that cost fractions of a cent. Checks that can never be proven from a configuration (a real inbound
call, an Event Grid delivery, recognition quality on telephone audio, legal review) are always listed as UNVERIFIED so a
green report cannot be mistaken for a working phone line. ``--provider asterisk`` checks the free local SIP path: its
settings, the Asterisk configuration in the repository and, online, one SIP OPTIONS and one TCP connect.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Self

import httpx
from pydantic import model_validator

from sparta.config import Settings
from sparta.doctor import asterisk as asterisk_checks
from sparta.doctor import asterisk_conf
from sparta.doctor import checks as c
from sparta.doctor.model import Check, DoctorReport, Status

PROVIDERS = ("azure", "twilio", "asterisk", "simulator")


class ReportingSettings(Settings):
    """Settings that report a production problem instead of raising it: the doctor lists every problem as a check."""

    @model_validator(mode="after")
    def _enforce(self) -> Self:
        return self


def load_settings(env_file: str | None = None) -> Settings:
    """The settings of this process from the environment and ``.env`` (or ``env_file``), without the fail-fast production guard."""
    return ReportingSettings(_env_file=env_file) if env_file else ReportingSettings()


def normalise_providers(requested: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    for name in requested:
        for resolved in PROVIDERS if name == "all" else (name,):
            if resolved not in names:
                names.append(resolved)
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        raise ValueError("unknown provider: " + ", ".join(unknown))
    return tuple(names)


def _shared_offline(settings: Settings, telephony: str) -> list[Check]:
    """Speech, language-model and limit checks: the same whichever telephony provider carries the call."""
    return [
        *c.speech_checks(settings),
        c.speech_sdk_check(settings),
        *c.openai_checks(settings),
        *c.limit_checks(settings),
        c.media_format_check(telephony),
    ]


def azure_offline(settings: Settings, callback_url: str | None) -> list[Check]:
    return [
        c.selection_check(settings, "azure"),
        c.acs_sdk_check(),
        c.acs_connection_string_check(settings),
        c.acs_resource_id_check(settings),
        c.callback_url_check(settings, callback_url),
        c.event_grid_check(settings),
        c.number_check(settings),
        *_shared_offline(settings, "azure"),
    ]


def twilio_offline(settings: Settings, callback_url: str | None) -> list[Check]:
    return [
        c.selection_check(settings, "twilio"),
        *c.twilio_credentials_check(settings),
        c.twilio_callback_url_check(settings, callback_url),
        *c.twilio_options_check(settings),
        c.number_check(settings, c.TWILIO, "the Twilio account"),
        *_shared_offline(settings, "twilio"),
    ]


def _choose(phone_text: str, sip_text: str, phone: bool, asterisk: bool, joiner: str) -> str:
    """The wording for the providers being checked: each kind's own sentence, joined when both kinds are."""
    if not asterisk:
        return phone_text
    return f"{phone_text}{joiner}{sip_text}" if phone else sip_text


def unverified_checks(
    settings: Settings, *, azure: bool = True, twilio: bool = False, asterisk: bool = False
) -> list[Check]:
    """What a configuration check cannot prove. Each line says how to prove it."""
    group = "Not provable from here"
    both = azure and twilio
    phone = azure or twilio  # a provider that reaches ordinary telephone numbers
    local_stt = settings.stt_provider == "local"
    out: list[Check] = []
    if phone:
        out.append(
            Check(
                "live.pstn_inbound",
                group,
                "A real telephone call reaching Sparta",
                Status.UNVERIFIED,
                "no real inbound call has ever been completed through this project.",
                "Place a call to the provider number and follow docs/TELEPHONY.md, 'Live-test checklist'.",
            )
        )
    if asterisk:
        out.append(
            Check(
                "live.sip_call",
                group,
                "A real SIP client call reaching Sparta",
                Status.UNVERIFIED,
                "a configuration check cannot show that a SIP client can register, hear the assistant and be heard. Local "
                "SIP is not a phone-number connection: an ordinary mobile or landline number cannot reach Sparta through "
                "Asterisk without a carrier, a number and a trunk, which this setup deliberately does not have.",
                "Register a SIP client (docs/ANDROID_SIP_TESTING.md), dial the Sparta extension and talk to the assistant. "
                "No audio, or audio in one direction only, usually means the RTP ports are not reachable.",
                keep_numbers=True,
            )
        )
    if azure:
        out.append(
            Check(
                "live.event_grid_subscription",
                group,
                "Event Grid subscription delivering IncomingCall events",
                Status.UNVERIFIED,
                "it lives in Azure, not in this configuration.",
                "`az eventgrid event-subscription show` (docs/TELEPHONY.md) and one delivered call.",
            )
        )
    if twilio:
        out.append(
            Check(
                "live.twilio_media_stream",
                group,
                "Twilio opening the media WebSocket",
                Status.UNVERIFIED,
                "the TwiML, the stream parameters and the signature of the WebSocket upgrade follow Twilio's "
                "documentation but were only exercised against fakes. Both URL forms Twilio may sign (wss and "
                "https) are accepted.",
                "Place one call and read the 'media socket rejected' and 'webhook rejected' log lines, if any.",
            )
        )
    barge_phone = (
        "the "
        + ("StopAudio frame and the pacing of outbound audio were" if not twilio or both else "clear message was")
        + " only exercised against a fake media socket."
    )
    barge_sip = (
        "the paced 20 ms frames of outbound audio and the stop on interruption were exercised against a scripted "
        "AudioSocket client; the delay a caller hears on a real SIP call is not known until it is measured."
    )
    recognition_phone = (
        "no Hindi, Kannada or code-switched caller audio has been recognised by the real service in this project."
    )
    recognition_sip = (
        "a SIP call carries 8 kHz G.711 audio, which recognition handles less accurately than 16 kHz, and Hindi, Kannada "
        "and code-switched callers have not been measured on real telephone audio"
        + (" (Kannada recognition by the local model is experimental)." if local_stt else ".")
    )
    takeover_phone = "transfer was only exercised against a fake client." + (
        " Twilio trial accounts cannot dial out from a call at all." if twilio else ""
    )
    takeover_sip = "Take Over rings the owner's SIP extension on the local server; that was only exercised against scripted clients."
    fix_phone = "Test with SPARTA takeover number set to a phone you control."
    fix_sip = "Register a SIP phone as the owner extension, call Sparta from another SIP client and press Take Over in the app."
    out += [
        Check(
            "live.barge_in",
            group,
            "Interrupting the assistant on a real line",
            Status.UNVERIFIED,
            _choose(barge_phone, barge_sip, phone, asterisk, " For Asterisk, "),
            "Interrupt a live call and read the 'interruption' latency in the call's diagnostic report.",
            keep_numbers=asterisk,
        ),
        Check(
            "live.recognition_quality",
            group,
            "Recognition quality of telephone audio, Hinglish and Kanglish",
            Status.UNVERIFIED,
            _choose(recognition_phone, recognition_sip, phone, asterisk, " For Asterisk, "),
            "Record consented test calls and compare the transcripts with what was said before trusting any language.",
            keep_numbers=asterisk,
        ),
        Check(
            "live.takeover",
            group,
            "Transferring a live call to the owner",
            Status.UNVERIFIED,
            _choose(takeover_phone, takeover_sip, phone, asterisk, " "),
            _choose(fix_phone, fix_sip, phone, asterisk, " For Asterisk: "),
            keep_numbers=asterisk,
        ),
        Check(
            "legal.review",
            group,
            "Legal review (AI disclosure, recording, interception, number use, retention)",
            Status.UNVERIFIED,
            "this project makes no legal claim and has had no legal review.",
            "Work through the legal-review checklist in docs/PRIVACY.md before any real caller is involved.",
        ),
    ]
    return out


async def run_doctor(
    settings: Settings,
    *,
    providers: Sequence[str] = ("azure",),
    online: bool = False,
    allow_billable: bool = False,
    callback_url: str | None = None,
    http: httpx.AsyncClient | None = None,
    timeout_s: float = 8.0,
    asterisk_dir: Path | None = None,
) -> DoctorReport:
    names = normalise_providers(providers)
    report = DoctorReport(providers=names, online=online, billable=online and allow_billable)
    azure, twilio, sip = "azure" in names, "twilio" in names, "asterisk" in names
    report.extend(c.core_checks(settings, callback_url=callback_url))
    if azure:
        report.extend(azure_offline(settings, callback_url))
    if twilio:
        report.extend(twilio_offline(settings, callback_url))
    config = asterisk_conf.load(asterisk_conf.find_directory(asterisk_dir) if sip else None)
    if sip:
        report.extend(asterisk_checks.asterisk_offline(settings, config))
    # Asterisk's speech and model are Azure's only when the settings choose them (the free path is local)
    sip_azure = sip and (
        "azure" in (settings.stt_provider, settings.tts_provider) or settings.llm_provider == "azure_openai"
    )
    if online:
        from sparta.doctor.online import run_online

        owns = http is None
        client = http or httpx.AsyncClient(timeout=timeout_s, follow_redirects=False)
        try:
            report.extend(
                await run_online(
                    settings,
                    azure=azure,
                    twilio=twilio,
                    asterisk=sip,
                    callback_url=callback_url,
                    http=client,
                    timeout_s=timeout_s,
                    rtp_range=asterisk_conf.rtp_range(config) if sip else None,
                )
            )
            if (azure or twilio or sip_azure) and allow_billable:
                from sparta.doctor.billable import run_billable

                report.extend(await run_billable(settings, http=client, timeout_s=timeout_s))
        finally:
            if owns:
                await client.aclose()
    if azure or twilio or sip:
        report.extend(unverified_checks(settings, azure=azure, twilio=twilio, asterisk=sip))
    else:
        report.add(
            Check(
                "doctor.scope",
                "Core",
                "Only the core checks ran",
                Status.WARNING,
                "--provider simulator checks the process and storage, not a phone line.",
                "Use --provider azure, --provider twilio or --provider asterisk to check the real telephony and speech "
                "path.",
            )
        )
    return report
