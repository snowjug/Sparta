"""Deterministic, ASR-like noise for robustness runs.

This is a *synthetic* stand-in for recognition errors (dropped words, swapped letters). Real recognisers fail in other
ways (homophones, code-switch confusion, truncated words), so results under this noise are an indication of how fast
the rules degrade, not a prediction of accuracy on real audio.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class NoiseModel:
    level: float  # 0.0 = none; roughly the share of words affected (half dropped, half corrupted)
    seed: str = "sparta-eval-noise-v1"

    def apply(self, text: str, scenario_id: str, turn_index: int) -> str:
        if self.level <= 0:
            return text
        rng = random.Random(f"{self.seed}:{scenario_id}:{turn_index}")  # reproducible noise  # noqa: S311  # nosec B311
        out: list[str] = []
        for token in text.split():
            roll = rng.random()
            if roll < self.level / 2:
                continue  # the word was lost
            if roll < self.level and len(token) >= 4:
                i = rng.randrange(1, len(token) - 2)
                out.append(token[:i] + token[i + 1] + token[i] + token[i + 2 :])  # two neighbouring letters swapped
                continue
            out.append(token)
        return " ".join(out) if out else text
