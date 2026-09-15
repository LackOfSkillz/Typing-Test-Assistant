"""A virtual clock. Sleeps advance time instantly, so pacing tests finish fast."""

from __future__ import annotations

from typing import Callable, Optional


class FakeClock:
    """Records requested sleeps and advances virtual time by ``drift`` times each.

    ``drift`` models a machine that sleeps longer than asked: 1.2 means every
    sleep overruns by 20%. That is what the typist's closed-loop correction has
    to absorb.

    ``on_sleep(index, seconds)`` fires during each sleep, which is how a test
    simulates something happening *between* keystrokes -- a human touching the
    keyboard while the typist is waiting. That is the scenario that
    distinguishes checking the abort flag before a keystroke from after it.
    """

    def __init__(
        self,
        start: float = 0.0,
        drift: float = 1.0,
        on_sleep: Optional[Callable[[int, float], None]] = None,
    ) -> None:
        self._t = start
        self.drift = drift
        self.sleeps: list[float] = []
        self._on_sleep = on_sleep

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            self._t += seconds * self.drift
        if self._on_sleep is not None:
            self._on_sleep(len(self.sleeps), seconds)

    def close(self) -> None:
        pass
