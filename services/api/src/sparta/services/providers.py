"""Provider factory: adapters are chosen purely from configuration; credentials never leave ``Settings``.

Azure adapters are imported lazily so a simulator-only install never loads (or needs) their dependencies, and a
misconfigured selection fails at startup with an actionable message instead of at the first call.
"""

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from sparta.clock import Clock
from sparta.config import ConfigurationError, Settings
from sparta.observability.metrics import Metrics
from sparta.providers.base import ConversationModelProvider, SpeechToTextProvider, TextToSpeechProvider
from sparta.providers.llm.rules import RulesConversationModel
from sparta.providers.stt.simulator import SimulatedSpeechToText
from sparta.providers.tts.simulator import SimulatedTextToSpeech
from sparta.telephony.base import TelephonyProvider
from sparta.telephony.simulator import SimulatorTelephonyProvider

log = logging.getLogger("sparta.providers")


@dataclass
class ProviderSet:
    telephony: TelephonyProvider
    sim_telephony: SimulatorTelephonyProvider
    stt: SpeechToTextProvider
    tts: TextToSpeechProvider
    llm: ConversationModelProvider
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def aclose(self) -> None:
        for close in reversed(self.closers):
            try:
                await close()
            except Exception:  # shutdown must continue even if one adapter fails to close
                log.warning("provider close failed", exc_info=True)


def _load_plugin(spec: str) -> Callable[..., TelephonyProvider]:
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ConfigurationError([f"SPARTA_TELEPHONY_PLUGIN must look like 'package.module:factory', got '{spec}'"])
    try:
        factory = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise ConfigurationError([f"Cannot load telephony plugin '{spec}': {exc.__class__.__name__}"]) from exc
    if not callable(factory):
        raise ConfigurationError([f"Telephony plugin '{spec}' is not callable"])
    return factory  # type: ignore[no-any-return]


def build_providers(settings: Settings, *, clock: Clock, metrics: Metrics) -> ProviderSet:
    """Instantiate the configured adapters. The simulator telephony adapter is always present (Simulator Lab)."""
    closers: list[Callable[[], Awaitable[None]]] = []
    http: httpx.AsyncClient | None = None

    def shared_http() -> httpx.AsyncClient:
        nonlocal http
        if http is None:
            http = httpx.AsyncClient(timeout=settings.provider_timeout_s, follow_redirects=False)
            closers.append(http.aclose)
        return http

    def register(provider: Any) -> Any:
        close = getattr(provider, "aclose", None)
        if close is not None:
            closers.append(close)
        return provider

    sim_telephony = register(SimulatorTelephonyProvider(clock))

    stt: SpeechToTextProvider
    if settings.stt_provider == "azure":
        from sparta.providers.stt.azure import AzureSpeechToText

        stt = register(AzureSpeechToText(settings, http=shared_http(), clock=clock, metrics=metrics))
    else:
        stt = SimulatedSpeechToText()

    tts: TextToSpeechProvider
    if settings.tts_provider == "azure":
        from sparta.providers.tts.azure import AzureTextToSpeech

        tts = register(AzureTextToSpeech(settings, http=shared_http(), clock=clock, metrics=metrics))
    else:
        tts = SimulatedTextToSpeech()

    llm: ConversationModelProvider
    if settings.llm_provider == "azure_openai":
        from sparta.providers.llm.azure_openai import AzureOpenAIConversationModel

        llm = register(AzureOpenAIConversationModel(settings, http=shared_http(), clock=clock, metrics=metrics))
    else:
        llm = RulesConversationModel()

    telephony: TelephonyProvider
    if settings.telephony_provider == "azure":
        from sparta.telephony.azure_acs import build_acs_provider

        telephony = register(build_acs_provider(settings, tts=tts, http=shared_http(), clock=clock, metrics=metrics))
    elif settings.telephony_provider == "other":
        assert settings.telephony_plugin is not None  # enforced by Settings.problems()
        telephony = register(_load_plugin(settings.telephony_plugin)(settings, tts=tts, clock=clock, metrics=metrics))
    else:
        telephony = sim_telephony

    return ProviderSet(telephony=telephony, sim_telephony=sim_telephony, stt=stt, tts=tts, llm=llm, closers=closers)
