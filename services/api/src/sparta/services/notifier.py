"""Owner notifications.

Push delivery to a phone needs a platform account (Firebase Cloud Messaging / Apple Push) that cannot be created in this
repository, so only the port and non-delivering adapters ship. Escalations still reach a connected app immediately over
the live WebSocket, and the Android app also polls (battery-conscious WorkManager). See ``docs/ANDROID_SETUP.md``.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol

log = logging.getLogger("sparta.notify")


@dataclass(frozen=True)
class PushNotification:
    kind: Literal["escalation", "high_risk"]
    call_id: str
    title: str
    body: str
    important_lines: list[str] = field(default_factory=list)


class PushNotifier(Protocol):
    name: str
    delivers: bool

    async def notify(self, user_id: str, notification: PushNotification) -> None: ...


class NullPushNotifier:
    name = "none"
    delivers = False

    async def notify(self, user_id: str, notification: PushNotification) -> None:
        return None


class LoggingPushNotifier:
    """Logs that a push *would* be sent (identifiers only, never content). It does not deliver anything."""

    name = "log"
    delivers = False

    async def notify(self, user_id: str, notification: PushNotification) -> None:
        log.info(
            "push not delivered (no push provider configured)",
            extra={"kind": notification.kind, "call_id": notification.call_id},
        )


class RecordingPushNotifier:
    """Test double that keeps what would have been sent."""

    name = "recording"
    delivers = False

    def __init__(self) -> None:
        self.sent: list[tuple[str, PushNotification]] = []

    async def notify(self, user_id: str, notification: PushNotification) -> None:
        self.sent.append((user_id, notification))
