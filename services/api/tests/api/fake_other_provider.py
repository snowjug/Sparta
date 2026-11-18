"""A stand-in third-party telephony plugin (TELEPHONY_PROVIDER=other) for webhook tests."""

import dataclasses

from sparta.clock import Clock
from sparta.config import Settings
from sparta.domain.enums import ProviderKind
from sparta.observability.metrics import Metrics
from sparta.providers.base import TextToSpeechProvider
from sparta.telephony.base import TelephonyProvider
from sparta.telephony.simulator import SIMULATOR_CAPABILITIES, SimulatorTelephonyProvider


class OtherProvider(SimulatorTelephonyProvider):
    name = "other"
    kind = ProviderKind.OTHER
    capabilities = dataclasses.replace(
        SIMULATOR_CAPABILITIES, simulated=False, live_calls_supported=True, note="test plugin (not simulated)"
    )


def factory(settings: Settings, *, tts: TextToSpeechProvider, clock: Clock, metrics: Metrics) -> TelephonyProvider:
    return OtherProvider(clock)
