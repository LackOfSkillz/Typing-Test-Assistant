"""Walking a keystroke schedule against a clock and a keyboard.

Pure module. Time and keystrokes arrive as injected objects, which is what makes
abort latency and drift correction testable without sending anything real.

Two guarantees matter here:

* The abort flag is checked *before* every keystroke, so worst-case stop latency
  is one character -- about 20 ms at 55 WPM. The old implementation ignored its
  hotkey entirely once typing began (``main.py:64``).
* Cumulative elapsed time is steered back toward cumulative planned time, with
  the per-step correction clamped so convergence is never visible as a speed
  jump.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from typing_assistant.core.pacing import Keystroke, measured_wpm

#: Characters between closed-loop corrections. Measured: 8 tracks a drifting
#: clock noticeably better than 24 (3.99% vs 4.86% residual error at drift 1.2)
#: for one extra division every eight characters.
DEFAULT_CORRECTION_INTERVAL = 8

#: Bounds on the correction multiplier. A 25% adjustment absorbs realistic
#: timer error while staying below the threshold of looking unnatural.
MIN_SCALE = 0.75
MAX_SCALE = 1.25


@dataclass(frozen=True)
class TypeResult:
    """What a run actually did."""

    sent: str
    aborted: bool
    elapsed: float
    wpm: float


def type_schedule(
    keystrokes: Sequence[Keystroke],
    keyboard,
    clock,
    abort: Optional[object] = None,
    cursor: Optional[object] = None,
    correction_interval: int = DEFAULT_CORRECTION_INTERVAL,
) -> TypeResult:
    """Type *keystrokes*, returning what was sent and how fast.

    *keyboard* needs ``send_char(str)``. *clock* needs ``now()`` and
    ``sleep(float)``. *abort*, if given, needs ``is_set()``. *cursor*, if given,
    needs ``take(int)`` and is advanced one character per keystroke so a paused
    run knows exactly how far it got.
    """
    if not keystrokes:
        return TypeResult(sent="", aborted=False, elapsed=0.0, wpm=0.0)

    total_planned = math.fsum(k.delay for k in keystrokes)
    start = clock.now()
    planned_so_far = 0.0
    scale = 1.0
    sent: list[str] = []
    aborted = False

    for index, keystroke in enumerate(keystrokes):
        if abort is not None and abort.is_set():
            aborted = True
            break

        clock.sleep(keystroke.delay * scale)
        keyboard.send_char(keystroke.char)
        sent.append(keystroke.char)
        if cursor is not None:
            cursor.take(1)

        planned_so_far += keystroke.delay

        if correction_interval > 0 and (index + 1) % correction_interval == 0:
            remaining_planned = total_planned - planned_so_far
            if remaining_planned > 0:
                remaining_budget = total_planned - (clock.now() - start)
                desired = remaining_budget / remaining_planned
                scale = min(MAX_SCALE, max(MIN_SCALE, desired))

    elapsed = clock.now() - start
    return TypeResult(
        sent="".join(sent),
        aborted=aborted,
        elapsed=elapsed,
        wpm=measured_wpm(len(sent), elapsed),
    )
