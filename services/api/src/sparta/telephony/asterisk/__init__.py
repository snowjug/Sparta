"""Asterisk (local SIP) telephony adapter. See ``provider.py`` and ``docs/DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md``."""

from sparta.telephony.asterisk.provider import (
    ENDED_PATH,
    INCOMING_PATH,
    NEXT_PATH,
    AsteriskTelephonyProvider,
    IncomingDecision,
    build_asterisk_provider,
)

__all__ = [
    "ENDED_PATH",
    "INCOMING_PATH",
    "NEXT_PATH",
    "AsteriskTelephonyProvider",
    "IncomingDecision",
    "build_asterisk_provider",
]
