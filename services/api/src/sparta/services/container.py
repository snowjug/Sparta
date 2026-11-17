"""Composition root: the one place that decides which adapter implements which port.

``Container.build`` is used by the API process, the CLI and tests. ``hermetic=True`` builds a throw-away container
(in-memory SQLite, virtual clock, deterministic ids, in-process key-value store, simulator providers) that can never
touch the owner's data; the simulator's deterministic replay runs inside one.
"""

import logging
from dataclasses import dataclass
from typing import Self

from sparta.clock import Clock, SystemClock, VirtualClock
from sparta.config import ConfigurationError, Settings
from sparta.db.crypto import cipher_from_settings, pepper_from_settings
from sparta.db.session import Database, run_migrations
from sparta.db.types import has_cipher, set_cipher
from sparta.observability.metrics import Metrics
from sparta.observability.tracing import UnitCosts
from sparta.orchestrator.engine import ConversationEngine
from sparta.services.audio import AudioService
from sparta.services.calls import CallService
from sparta.services.ids import DeterministicIds, IdFactory, RandomIds
from sparta.services.kv import KeyValueStore, MemoryKV, RedisKV
from sparta.services.live import LiveHub
from sparta.services.notifier import LoggingPushNotifier, PushNotifier
from sparta.services.owner import OwnerService
from sparta.services.providers import ProviderSet, build_providers
from sparta.services.ratelimit import RateLimiter
from sparta.services.retention import RetentionService
from sparta.services.simulator import SimulatorService

log = logging.getLogger("sparta.container")


def unit_costs(settings: Settings) -> UnitCosts:
    return UnitCosts(
        stt_per_audio_hour=settings.estimated_stt_per_audio_hour_usd,
        tts_per_million_chars=settings.estimated_tts_per_million_chars_usd,
        llm_per_million_prompt_tokens=settings.estimated_llm_per_million_prompt_tokens_usd,
        llm_per_million_completion_tokens=settings.estimated_llm_per_million_completion_tokens_usd,
        telephony_per_minute=settings.estimated_telephony_per_minute_usd,
    )


@dataclass
class Container:
    settings: Settings
    clock: Clock
    ids: IdFactory
    metrics: Metrics
    db: Database
    kv: KeyValueStore
    hub: LiveHub
    limiter: RateLimiter
    engine: ConversationEngine
    providers: ProviderSet
    notifier: PushNotifier
    pepper: bytes
    calls: CallService
    owner: OwnerService
    simulator: SimulatorService
    audio: AudioService
    retention: RetentionService
    hermetic: bool = False
    started: bool = False

    @classmethod
    async def build(
        cls,
        settings: Settings,
        *,
        clock: Clock | None = None,
        ids: IdFactory | None = None,
        kv: KeyValueStore | None = None,
        notifier: PushNotifier | None = None,
        hermetic: bool = False,
    ) -> Self:
        problems = settings.problems()
        if problems:
            raise ConfigurationError(problems)
        if hermetic:
            clock = clock or VirtualClock()
            ids = ids or DeterministicIds()
            settings = settings.model_copy(
                update={
                    "database_url": "sqlite+aiosqlite:///:memory:",
                    "redis_url": None,
                    "stt_provider": "simulator",
                    "tts_provider": "simulator",
                    "llm_provider": "rules",
                    "telephony_provider": "simulator",
                    "feature_llm_summaries": False,
                }
            )
        clock = clock or SystemClock()
        ids = ids or RandomIds()
        metrics = Metrics()
        if not has_cipher():
            set_cipher(cipher_from_settings(settings))
        pepper = pepper_from_settings(settings)
        db = Database(settings.database_url)
        if kv is None:
            kv = RedisKV(settings.redis_url) if settings.redis_url else MemoryKV(clock)
        hub = LiveHub(kv)
        engine = ConversationEngine(clock=clock)
        providers = build_providers(settings, clock=clock, metrics=metrics)
        notifier = notifier or LoggingPushNotifier()
        calls = CallService(
            settings=settings,
            db=db,
            engine=engine,
            clock=clock,
            ids=ids,
            hub=hub,
            metrics=metrics,
            kv=kv,
            telephony=providers.telephony,
            sim_telephony=providers.sim_telephony,
            stt=providers.stt,
            tts=providers.tts,
            llm=providers.llm,
            notifier=notifier,
            pepper=pepper,
            costs=unit_costs(settings),
        )
        owner = OwnerService(
            settings=settings,
            db=db,
            clock=clock,
            ids=ids,
            engine=engine,
            providers=providers,
            calls=calls,
            pepper=pepper,
        )

        async def replay_container() -> Self:
            replay = await cls.build(settings, hermetic=True)
            await replay.start()  # creates the in-memory schema and binds the simulator telephony
            return replay

        simulator = SimulatorService(
            settings=settings,
            db=db,
            clock=clock,
            ids=ids,
            calls=calls,
            providers=providers,
            replay_factory=replay_container,
        )
        audio = AudioService(settings=settings, calls=calls, stt=providers.stt, metrics=metrics)
        retention = RetentionService(db, clock)
        return cls(
            settings=settings,
            clock=clock,
            ids=ids,
            metrics=metrics,
            db=db,
            kv=kv,
            hub=hub,
            limiter=RateLimiter(kv, clock=clock, metrics=metrics),
            engine=engine,
            providers=providers,
            notifier=notifier,
            pepper=pepper,
            calls=calls,
            owner=owner,
            simulator=simulator,
            audio=audio,
            retention=retention,
            hermetic=hermetic,
        )

    async def start(self) -> None:
        if self.started:
            return
        if self.hermetic or self.settings.database_url.startswith("sqlite+aiosqlite:///:memory:"):
            await self.db.create_all()
        elif self.settings.auto_migrate and not self.settings.is_production:
            await run_migrations(self.settings.database_url)
        await self.hub.start()
        self.calls.start()
        self.started = True

    async def stop(self) -> None:
        if not self.started:
            await self.db.dispose()
            return
        self.started = False
        await self.simulator.stop()
        await self.calls.stop()
        await self.hub.stop()
        await self.providers.aclose()
        await self.kv.aclose()
        await self.db.dispose()
