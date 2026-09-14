"""A virtual clock. Sleeps advance time instantly, so pacing tests finish fast."""

from __future__ import annotations


class FakeClock:
    """Records requested sleeps and advances virtual time by ``drift`` times each.

    ``drift`` models a machine that sleeps longer than asked: 1.2 means every
    sleep overruns by 20%. That is what the typist's closed-loop correction has
    to absorb.
    """

    def __init__(self, start: float = 0.0, drift: float = 1.0) -> None:
        self._t = start
        self.drift = drift
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            self._t += seconds * self.drift

    def close(self) -> None:
        pass
