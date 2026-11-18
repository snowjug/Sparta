"""Identifier generation. Deterministic in tests and in the simulator's replay mode."""

import hashlib
import itertools
import secrets
from typing import Protocol


class IdFactory(Protocol):
    def new(self, prefix: str) -> str: ...


class RandomIds:
    def new(self, prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(6)}"


class DeterministicIds:
    """Same seed, same sequence: a replayed scripted call produces byte-identical identifiers."""

    def __init__(self, seed: str = "replay") -> None:
        self._seed = seed
        self._counter = itertools.count(1)

    def new(self, prefix: str) -> str:
        digest = hashlib.sha256(f"{self._seed}:{prefix}:{next(self._counter)}".encode()).hexdigest()
        return f"{prefix}_{digest[:12]}"
