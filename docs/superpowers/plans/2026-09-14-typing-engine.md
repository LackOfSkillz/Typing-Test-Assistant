# Typing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Type a given block of text into any window at a genuinely accurate WPM, with a panic stop that works mid-typing and a pause that yields the keyboard the instant a human touches it.

**Architecture:** The timing loop and all arithmetic live in pure `core/` modules driven through injected clock and keyboard objects, so abort latency and closed-loop correction are unit-testable with no real keystrokes. The Windows edges — `SendInput`, `WH_KEYBOARD_LL`, high-resolution timers — are thin `adapters/` with fake counterparts. A CLI wires them together.

**Deliverable:** `python -m typing_assistant type --text "..." --wpm 55` arms, waits indefinitely for a go hotkey, then types. Any keypress pauses; the abort hotkey stops within one character. Usable on its own for forms, messages, or anything requiring sustained keystrokes — no OCR involved.

**Tech Stack:** Python 3.9+, `ctypes` (no new third-party dependencies), pytest, Hypothesis.

**Spec:** [`docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md`](../specs/2026-09-14-typing-assistant-redesign-design.md) — sections 5.1, 5.3, 6.6, 6.7, 6.8, 6.9, 9.4.

**Predecessor:** [`2026-09-14-core-and-practice-harness.md`](2026-09-14-core-and-practice-harness.md) (merged). This plan consumes `core.pacing`, `core.cursor` and `core.text` from it, unchanged.

## Global Constraints

- **Python floor: 3.9.** `from __future__ import annotations` in every module.
- **`core/` stays pure.** No `os`, `sys`, `time`, `ctypes`, `tkinter`, `cv2`, `PIL`, `pytesseract`, `pyautogui`, `pynput`, `threading` or `queue` imports. `tests/unit/test_core_purity.py` enforces this and must keep passing. Time and keystrokes reach `core/` only through injected objects.
- **Determinism.** Randomness only via an injected `random.Random`.
- **No new runtime dependencies.** Everything here is `ctypes` against Win32. Do not add `pywin32`.
- **Keystroke signature is `0x54595041`.** Validated by the spike in spec §8. Every synthetic event carries it in `dwExtraInfo`.
- **Tests that inject real keystrokes are marked `@pytest.mark.manual`** and excluded from the default run. CI must stay green headless.
- **Licence: 0BSD.** No copyright headers in source files.
- **Commit after every task.** Conventional-commit prefixes.

---

### Task 1: Clock adapter and FakeClock

The spike measured Windows' default `time.sleep` granularity at ~15.6 ms, which is 7% jitter on the ~218 ms interval of 55 WPM — enough to distort rhythm that the pacing engine carefully shaped. A high-resolution waitable timer is preferred over `timeBeginPeriod(1)` because it does not alter a global system setting on the user's behalf.

**Files:**
- Create: `typing_assistant/adapters/__init__.py`
- Create: `typing_assistant/adapters/clock.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/clock.py`
- Test: `tests/unit/test_clock_fake.py`
- Test: `tests/manual/__init__.py`
- Test: `tests/manual/test_clock_real.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SystemClock` with `now() -> float`, `sleep(seconds: float) -> None`, `close() -> None`, and `high_resolution: bool`
  - `FakeClock(start: float = 0.0, drift: float = 1.0)` with the same `now`/`sleep`, plus `sleeps: list[float]` recording every requested duration

- [ ] **Step 1: Register the `manual` marker and exclude it by default**

Replace the `[tool.pytest.ini_options]` block in `pyproject.toml` with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers -m 'not manual'"
markers = [
    "manual: injects real keystrokes or needs a focused window; excluded from the default run",
]
```

- [ ] **Step 2: Create package directories**

```bash
mkdir -p typing_assistant/adapters tests/fixtures tests/manual
touch typing_assistant/adapters/__init__.py tests/fixtures/__init__.py tests/manual/__init__.py
```

- [ ] **Step 3: Write FakeClock**

```python
# tests/fixtures/clock.py
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
```

- [ ] **Step 4: Write the failing FakeClock tests**

```python
# tests/unit/test_clock_fake.py
from __future__ import annotations

import pytest

from tests.fixtures.clock import FakeClock


def test_starts_at_given_time():
    assert FakeClock(start=5.0).now() == 5.0


def test_sleep_advances_virtual_time():
    c = FakeClock()
    c.sleep(0.25)
    assert c.now() == pytest.approx(0.25)


def test_sleep_records_requested_durations():
    c = FakeClock()
    c.sleep(0.1)
    c.sleep(0.2)
    assert c.sleeps == [0.1, 0.2]


def test_drift_makes_sleeps_overrun():
    c = FakeClock(drift=1.5)
    c.sleep(1.0)
    assert c.now() == pytest.approx(1.5)
    assert c.sleeps == [1.0], "records what was asked for, not what elapsed"


def test_zero_and_negative_sleeps_do_not_move_time():
    c = FakeClock()
    c.sleep(0.0)
    c.sleep(-1.0)
    assert c.now() == 0.0
```

- [ ] **Step 5: Run to verify they pass**

Run: `pytest tests/unit/test_clock_fake.py -v`
Expected: 5 passed.

- [ ] **Step 6: Write the real clock adapter**

```python
# typing_assistant/adapters/clock.py
"""High-resolution sleeping.

Windows' default timer granularity is ~15.6 ms. At 55 WPM a character interval
is ~218 ms, so that granularity is 7% jitter -- enough to distort the rhythm
core.pacing shaped deliberately. A high-resolution waitable timer fixes this
without calling timeBeginPeriod, which would change a global system setting.

Requires Windows 10 1803 or newer for CREATE_WAITABLE_TIMER_HIGH_RESOLUTION;
falls back to time.sleep otherwise, and reports which it got.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_CREATE_WAITABLE_TIMER_MANUAL_RESET = 0x00000001
_CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
_TIMER_ALL_ACCESS = 0x1F0003
_INFINITE = 0xFFFFFFFF

_k32.CreateWaitableTimerExW.argtypes = (
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
)
_k32.CreateWaitableTimerExW.restype = wintypes.HANDLE
_k32.SetWaitableTimer.argtypes = (
    wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_longlong),
    ctypes.c_long,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.BOOL,
)
_k32.SetWaitableTimer.restype = wintypes.BOOL
_k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)


class SystemClock:
    """Real time source. ``high_resolution`` says whether the timer was available."""

    def __init__(self) -> None:
        self._handle = _k32.CreateWaitableTimerExW(
            None,
            None,
            _CREATE_WAITABLE_TIMER_MANUAL_RESET
            | _CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
            _TIMER_ALL_ACCESS,
        )
        self.high_resolution = bool(self._handle)

    def now(self) -> float:
        return time.perf_counter()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if not self._handle:
            time.sleep(seconds)
            return
        # Negative means a relative interval, in units of 100 nanoseconds.
        due = ctypes.c_longlong(-int(seconds * 10_000_000))
        if not _k32.SetWaitableTimer(self._handle, ctypes.byref(due), 0, None, None, False):
            time.sleep(seconds)
            return
        _k32.WaitForSingleObject(self._handle, _INFINITE)

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None
            self.high_resolution = False

    def __enter__(self) -> "SystemClock":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

- [ ] **Step 7: Write the real-clock accuracy test**

Marked `manual` because it asserts wall-clock behaviour and is timing-sensitive on a shared CI runner.

```python
# tests/manual/test_clock_real.py
from __future__ import annotations

import statistics
import time

import pytest

from typing_assistant.adapters.clock import SystemClock

pytestmark = pytest.mark.manual


def test_high_resolution_timer_is_available():
    with SystemClock() as clock:
        assert clock.high_resolution, "needs Windows 10 1803+"


def test_short_sleeps_beat_default_granularity():
    """A 5 ms sleep must not take ~15.6 ms, which is what time.sleep gives."""
    target = 0.005
    with SystemClock() as clock:
        samples = []
        for _ in range(20):
            start = clock.now()
            clock.sleep(target)
            samples.append(clock.now() - start)

    median = statistics.median(samples)
    assert median < 0.010, f"median {median * 1000:.2f} ms, expected well under 10 ms"


def test_sleep_does_not_undershoot():
    target = 0.020
    with SystemClock() as clock:
        start = clock.now()
        clock.sleep(target)
        elapsed = clock.now() - start
    assert elapsed >= target * 0.9


def test_reference_time_sleep_granularity_for_comparison():
    """Records what we are improving on; informational, always passes."""
    samples = []
    for _ in range(10):
        start = time.perf_counter()
        time.sleep(0.005)
        samples.append(time.perf_counter() - start)
    print(f"\ntime.sleep(5ms) median: {statistics.median(samples) * 1000:.2f} ms")
```

- [ ] **Step 8: Run the manual tests explicitly**

Run: `pytest tests/manual/test_clock_real.py -v -m manual -s`
Expected: 4 passed. Note the printed `time.sleep` median for comparison — on stock Windows it is around 15 ms while the waitable timer should be near 5 ms.

- [ ] **Step 9: Confirm the default run still excludes them**

Run: `pytest`
Expected: all pass, and the summary shows `4 deselected` (the manual tests).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml typing_assistant/adapters tests/fixtures tests/manual tests/unit/test_clock_fake.py
git commit -m "feat: add high-resolution clock adapter and FakeClock"
```

---

### Task 2: The typing loop

Pure logic: walks a schedule, checks abort between every keystroke, and closed-loop corrects so cumulative elapsed tracks cumulative planned. Lives in `core/` and is driven entirely through injected objects, which is what makes abort latency testable without sending a single real keystroke.

**Files:**
- Create: `typing_assistant/core/typist.py`
- Create: `tests/fixtures/keyboard.py`
- Test: `tests/unit/test_typist.py`

**Interfaces:**
- Consumes: `core.pacing.Keystroke`, `core.pacing.measured_wpm`, `core.cursor.TypedCursor`, `tests.fixtures.clock.FakeClock`.
- Produces:
  - `@dataclass(frozen=True) TypeResult(sent: str, aborted: bool, elapsed: float, wpm: float)`
  - `DEFAULT_CORRECTION_INTERVAL: int` (= 8)
  - `MIN_SCALE: float` (= 0.75), `MAX_SCALE: float` (= 1.25)
  - `type_schedule(keystrokes, keyboard, clock, abort=None, cursor=None, correction_interval=DEFAULT_CORRECTION_INTERVAL) -> TypeResult`
  - `FakeKeyboard` with `sent: list[str]`, `text` property, `send_char(ch)`, `send_backspace()`, and an optional `on_send` callback

- [ ] **Step 1: Write FakeKeyboard**

```python
# tests/fixtures/keyboard.py
"""Records what would have been typed, instead of typing it."""

from __future__ import annotations

from typing import Callable, Optional


class FakeKeyboard:
    """Captures every character. ``on_send`` fires after each one.

    The callback is how tests trigger an abort partway through a run, which is
    what proves the abort check happens between keystrokes.
    """

    def __init__(self, on_send: Optional[Callable[[int, str], None]] = None) -> None:
        self.sent: list[str] = []
        self.backspaces = 0
        self._on_send = on_send

    @property
    def text(self) -> str:
        return "".join(self.sent)

    def send_char(self, ch: str) -> None:
        self.sent.append(ch)
        if self._on_send is not None:
            self._on_send(len(self.sent), ch)

    def send_backspace(self) -> None:
        self.backspaces += 1
        if self.sent:
            self.sent.pop()
```

- [ ] **Step 2: Write the failing typist tests**

```python
# tests/unit/test_typist.py
from __future__ import annotations

import random
import threading

import pytest

from tests.fixtures.clock import FakeClock
from tests.fixtures.keyboard import FakeKeyboard
from typing_assistant.core.cursor import TypedCursor
from typing_assistant.core.pacing import (
    PacingConfig,
    measured_wpm,
    schedule,
    target_duration,
    total_duration,
)
from typing_assistant.core.typist import (
    DEFAULT_CORRECTION_INTERVAL,
    TypeResult,
    type_schedule,
)

TEXT = "The quick brown fox jumps over the lazy dog. " * 3


def _schedule(wpm=55.0, text=TEXT, seed=1):
    return schedule(text, PacingConfig(wpm=wpm), random.Random(seed))


# --- basic behaviour ---

def test_types_every_character_in_order():
    ks = _schedule()
    kb, clock = FakeKeyboard(), FakeClock()
    result = type_schedule(ks, kb, clock)
    assert kb.text == TEXT
    assert result.sent == TEXT
    assert result.aborted is False


def test_sleeps_before_each_character():
    ks = _schedule(text="abc")
    kb, clock = FakeKeyboard(), FakeClock()
    type_schedule(ks, kb, clock)
    assert len(clock.sleeps) == 3


def test_reports_measured_wpm():
    ks = _schedule(wpm=55.0)
    kb, clock = FakeKeyboard(), FakeClock()
    result = type_schedule(ks, kb, clock)
    assert result.wpm == pytest.approx(55.0, abs=0.5)
    assert result.elapsed == pytest.approx(target_duration(len(TEXT), 55.0), rel=0.02)


def test_empty_schedule_is_a_noop():
    kb, clock = FakeKeyboard(), FakeClock()
    result = type_schedule((), kb, clock)
    assert result == TypeResult(sent="", aborted=False, elapsed=0.0, wpm=0.0)


def test_result_is_frozen():
    r = TypeResult(sent="a", aborted=False, elapsed=1.0, wpm=10.0)
    with pytest.raises(Exception):
        r.sent = "b"  # type: ignore[misc]


# --- abort latency: the safety requirement ---

def test_abort_stops_within_one_keystroke():
    """Set from inside the keyboard after char 10; char 11 must never be sent."""
    abort = threading.Event()
    kb = FakeKeyboard(on_send=lambda n, ch: abort.set() if n == 10 else None)
    clock = FakeClock()
    result = type_schedule(_schedule(), kb, clock, abort=abort)
    assert len(kb.sent) == 10, "abort must be checked before every keystroke"
    assert result.aborted is True
    assert result.sent == TEXT[:10]


def test_abort_set_before_starting_sends_nothing():
    abort = threading.Event()
    abort.set()
    kb, clock = FakeKeyboard(), FakeClock()
    result = type_schedule(_schedule(), kb, clock, abort=abort)
    assert kb.sent == []
    assert result.aborted is True


def test_abort_never_set_completes():
    abort = threading.Event()
    kb, clock = FakeKeyboard(), FakeClock()
    result = type_schedule(_schedule(), kb, clock, abort=abort)
    assert result.aborted is False
    assert kb.text == TEXT


# --- cursor integration ---

def test_cursor_advances_with_every_character():
    cursor = TypedCursor()
    cursor.observe(TEXT)
    kb, clock = FakeKeyboard(), FakeClock()
    type_schedule(_schedule(), kb, clock, cursor=cursor)
    assert cursor.emitted == TEXT
    assert cursor.pending == ""


def test_cursor_records_only_what_was_sent_when_aborted():
    cursor = TypedCursor()
    cursor.observe(TEXT)
    abort = threading.Event()
    kb = FakeKeyboard(on_send=lambda n, ch: abort.set() if n == 12 else None)
    type_schedule(_schedule(), kb, clock=FakeClock(), abort=abort, cursor=cursor)
    assert cursor.emitted == TEXT[:12]
    assert cursor.pending == TEXT[12:]


# --- closed-loop correction ---

# Thresholds below are measured, not guessed. Simulated against the real
# core.pacing schedule with correction_interval=8 and the 0.75-1.25 clamp:
#
#     drift 0.90 -> 1.63% error      drift 1.10 -> 0.69%
#     drift 1.20 -> 3.99%            drift 1.50 -> 23.4% (clamp-limited)
#     uncorrected, any drift d       -> |d - 1| exactly
#
# Real hardware drift is nothing like this. The spike measured SendInput
# overhead at 0.8% of a 55 WPM interval, and systematic error is removed by
# per-machine calibration; this loop only absorbs what is left.

def test_drifting_clock_is_corrected():
    """A machine sleeping 20% long must still land near the target duration."""
    ks = _schedule(wpm=55.0)
    target = total_duration(ks)

    uncorrected = FakeClock(drift=1.2)
    type_schedule(ks, FakeKeyboard(), uncorrected, correction_interval=10**9)
    uncorrected_error = abs(uncorrected.now() - target) / target

    corrected = FakeClock(drift=1.2)
    type_schedule(ks, FakeKeyboard(), corrected)
    corrected_error = abs(corrected.now() - target) / target

    assert uncorrected_error > 0.15, "sanity: undriven drift should show up"
    assert corrected_error < 0.06, f"correction left {corrected_error:.1%} error"
    assert corrected_error < uncorrected_error / 2


def test_fast_clock_is_also_corrected():
    """A clock running 10% fast is slowed back toward the target."""
    ks = _schedule(wpm=55.0)
    target = total_duration(ks)
    clock = FakeClock(drift=0.9)
    type_schedule(ks, FakeKeyboard(), clock)
    assert abs(clock.now() - target) / target < 0.04


def test_extreme_drift_is_limited_by_the_clamp():
    """Characterises a deliberate trade-off rather than asserting perfection.

    Fully countering drift *d* needs an average scale of 1/d. Outside the
    0.75-1.25 clamp that is not permitted, because a larger correction would be
    visible as a speed jump. Natural rhythm wins over hitting the target
    exactly, so a 50%-slow machine is improved but not fixed.
    """
    ks = _schedule(wpm=55.0)
    target = total_duration(ks)
    clock = FakeClock(drift=1.5)
    type_schedule(ks, FakeKeyboard(), clock)
    error = abs(clock.now() - target) / target

    assert error < 0.50 / 2, "correction should at least halve a 50% overrun"
    assert error > 0.10, "and cannot eliminate it; the clamp binds"


def test_correction_never_makes_a_visible_jump():
    """No requested delay may differ from its neighbour by more than the clamp."""
    ks = _schedule(wpm=55.0)
    clock = FakeClock(drift=1.5)
    type_schedule(ks, FakeKeyboard(), clock)
    scales = [
        actual / planned.delay
        for actual, planned in zip(clock.sleeps, ks)
        if planned.delay > 0
    ]
    assert min(scales) >= 0.75 - 1e-9
    assert max(scales) <= 1.25 + 1e-9


def test_perfect_clock_needs_no_correction():
    ks = _schedule(wpm=55.0)
    clock = FakeClock(drift=1.0)
    type_schedule(ks, FakeKeyboard(), clock)
    for actual, planned in zip(clock.sleeps, ks):
        assert actual == pytest.approx(planned.delay, rel=1e-6)


def test_default_correction_interval():
    assert DEFAULT_CORRECTION_INTERVAL == 8
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_typist.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'typing_assistant.core.typist'`

- [ ] **Step 4: Write the implementation**

```python
# typing_assistant/core/typist.py
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


class _Abort:
    """Duck-type documentation: anything with ``is_set()`` works.

    ``threading.Event`` satisfies this in production.
    """

    def is_set(self) -> bool:  # pragma: no cover - documentation only
        raise NotImplementedError


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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_typist.py -v`
Expected: all pass. If `test_drifting_clock_is_corrected` fails on the sanity assertion, the drift model is not being applied — check `FakeClock.sleep`.

- [ ] **Step 6: Confirm core is still pure**

Run: `pytest tests/unit/test_core_purity.py -v`
Expected: 3 passed. `typist.py` imports only `math`, `dataclasses`, `typing` and sibling core modules.

- [ ] **Step 7: Commit**

```bash
git add typing_assistant/core/typist.py tests/fixtures/keyboard.py tests/unit/test_typist.py
git commit -m "feat: add typing loop with one-keystroke abort and drift correction"
```

---

### Task 3: Calibration arithmetic

Replaces `CALIBRATION_FACTOR = 34 / 50` at `main.py:172` with a measured, per-machine value.

**Files:**
- Create: `typing_assistant/core/calibration.py`
- Test: `tests/unit/test_calibration.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MIN_FACTOR: float` (= 0.5), `MAX_FACTOR: float` (= 2.0), `DEFAULT_TOLERANCE: float` (= 2.0)
  - `calibration_factor(target_wpm, measured_wpm, previous=1.0) -> float`
  - `within_tolerance(target_wpm, measured_wpm, tolerance=DEFAULT_TOLERANCE) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_calibration.py
from __future__ import annotations

import pytest

from typing_assistant.core.calibration import (
    DEFAULT_TOLERANCE,
    MAX_FACTOR,
    MIN_FACTOR,
    calibration_factor,
    within_tolerance,
)


def test_accurate_measurement_leaves_the_factor_alone():
    assert calibration_factor(55.0, 55.0, previous=1.0) == pytest.approx(1.0)


def test_typing_too_slow_shortens_delays():
    # Asked for 55, got 44 -> delays must shrink, so the factor drops.
    factor = calibration_factor(55.0, 44.0, previous=1.0)
    assert factor == pytest.approx(0.8)
    assert factor < 1.0


def test_typing_too_fast_lengthens_delays():
    factor = calibration_factor(55.0, 66.0, previous=1.0)
    assert factor == pytest.approx(1.2)
    assert factor > 1.0


def test_correction_compounds_on_the_previous_factor():
    factor = calibration_factor(55.0, 44.0, previous=0.9)
    assert factor == pytest.approx(0.72)


def test_factor_is_clamped_low():
    assert calibration_factor(100.0, 1.0, previous=1.0) == pytest.approx(MIN_FACTOR)


def test_factor_is_clamped_high():
    assert calibration_factor(1.0, 100.0, previous=1.0) == pytest.approx(MAX_FACTOR)


def test_zero_measurement_keeps_the_previous_factor():
    # A failed measurement must not destroy a good calibration.
    assert calibration_factor(55.0, 0.0, previous=0.87) == pytest.approx(0.87)


def test_non_positive_target_is_rejected():
    with pytest.raises(ValueError):
        calibration_factor(0.0, 55.0)


def test_non_positive_previous_is_rejected():
    with pytest.raises(ValueError):
        calibration_factor(55.0, 55.0, previous=0.0)


def test_within_tolerance_default_is_two_wpm():
    assert DEFAULT_TOLERANCE == 2.0
    assert within_tolerance(55.0, 56.5) is True
    assert within_tolerance(55.0, 53.5) is True
    assert within_tolerance(55.0, 58.0) is False


def test_within_tolerance_boundary_is_inclusive():
    assert within_tolerance(55.0, 57.0) is True
    assert within_tolerance(55.0, 57.001) is False


def test_repeated_calibration_converges():
    """A machine that always runs 15% fast must settle after a few rounds.

    Model: with calibration *f*, delays are scaled by f, so the machine's true
    output is target * 1.15 / f.
    """
    target = 55.0
    factor = 1.0

    def machine_output(f: float) -> float:
        return target * 1.15 / f

    for _ in range(6):
        factor = calibration_factor(target, machine_output(factor), previous=factor)

    assert within_tolerance(target, machine_output(factor))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_calibration.py -v`
Expected: collection error — no module named `calibration`.

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/calibration.py
"""Deriving a per-machine timing correction from a measured run.

``core.pacing.schedule`` multiplies its whole schedule by ``PacingConfig
.calibration``. This module decides what that number should be, from what a
measured run actually produced.

Replaces the hand-tuned ``CALIBRATION_FACTOR = 34 / 50`` at ``main.py:172``,
which was a single constant fitted to one machine.

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

#: Bounds on the stored factor. Anything outside this range means the
#: measurement was wrong, not that the machine is that far off.
MIN_FACTOR = 0.5
MAX_FACTOR = 2.0

#: How close a measured run must be to count as calibrated, in WPM.
DEFAULT_TOLERANCE = 2.0


def calibration_factor(
    target_wpm: float, measured_wpm: float, previous: float = 1.0
) -> float:
    """Return the factor to store, given what a run at *previous* produced.

    Typing slower than asked means the delays were too long, so the factor
    shrinks. A measurement of zero -- a failed or aborted run -- returns
    *previous* unchanged rather than destroying a good calibration.
    """
    if target_wpm <= 0:
        raise ValueError("target_wpm must be positive")
    if previous <= 0:
        raise ValueError("previous must be positive")
    if measured_wpm <= 0:
        return previous

    adjusted = previous * (measured_wpm / target_wpm)
    return min(MAX_FACTOR, max(MIN_FACTOR, adjusted))


def within_tolerance(
    target_wpm: float, measured_wpm: float, tolerance: float = DEFAULT_TOLERANCE
) -> bool:
    """Is *measured_wpm* close enough to *target_wpm* to stop calibrating?"""
    return abs(measured_wpm - target_wpm) <= tolerance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_calibration.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add typing_assistant/core/calibration.py tests/unit/test_calibration.py
git commit -m "feat: add measured per-machine calibration replacing the magic constant"
```

---

### Task 4: Keystroke classification

Pure arithmetic over the exact flag and `dwExtraInfo` values the spike measured, so the injected-versus-human rule is unit-tested before any hook exists.

**Files:**
- Create: `typing_assistant/core/keyevents.py`
- Test: `tests/unit/test_keyevents.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SIGNATURE: int` (= 0x54595041)
  - `LLKHF_EXTENDED`, `LLKHF_LOWER_IL_INJECTED`, `LLKHF_INJECTED`, `LLKHF_ALTDOWN`, `LLKHF_UP`
  - `@dataclass(frozen=True) KeyEvent(vk: int, scan: int, flags: int, extra_info: int)` with properties `injected`, `ours`, `human`, `is_up`, `is_down`
  - `classify(vk, scan, flags, extra_info) -> KeyEvent`

- [ ] **Step 1: Write the failing tests**

Values come from spec §8 — the measured spike output, not invention.

```python
# tests/unit/test_keyevents.py
from __future__ import annotations

from typing_assistant.core.keyevents import (
    LLKHF_INJECTED,
    LLKHF_UP,
    SIGNATURE,
    KeyEvent,
    classify,
)

# Exactly what the spike observed (spec section 8).
TAGGED_DOWN = dict(vk=0x87, scan=0, flags=0x10, extra_info=SIGNATURE)
TAGGED_UP = dict(vk=0x87, scan=0, flags=0x90, extra_info=SIGNATURE)
HUMAN_DOWN = dict(vk=0x09, scan=0x0F, flags=0x00, extra_info=0x0)
HUMAN_UP = dict(vk=0x09, scan=0x0F, flags=0x80, extra_info=0x0)
OTHER_TOOL = dict(vk=0x41, scan=0x1E, flags=0x10, extra_info=0xDEADBEEF)


def test_signature_matches_the_validated_spike():
    assert SIGNATURE == 0x54595041


def test_our_tagged_event_is_recognised():
    e = classify(**TAGGED_DOWN)
    assert e.injected is True
    assert e.ours is True
    assert e.human is False


def test_real_keypress_is_human():
    e = classify(**HUMAN_DOWN)
    assert e.injected is False
    assert e.ours is False
    assert e.human is True


def test_another_tools_injection_is_not_ours_and_not_human():
    """Injected but unsigned: not our output, and not hands either."""
    e = classify(**OTHER_TOOL)
    assert e.injected is True
    assert e.ours is False
    assert e.human is False


def test_signature_without_the_injected_flag_is_not_ours():
    """Both discriminators are required, so the tag alone cannot be spoofed."""
    e = classify(vk=0x41, scan=0x1E, flags=0x00, extra_info=SIGNATURE)
    assert e.ours is False
    assert e.human is True


def test_key_up_and_down_are_distinguished():
    assert classify(**HUMAN_DOWN).is_down is True
    assert classify(**HUMAN_DOWN).is_up is False
    assert classify(**HUMAN_UP).is_up is True
    assert classify(**TAGGED_UP).is_up is True
    assert classify(**TAGGED_DOWN).is_down is True


def test_flag_constants():
    assert LLKHF_INJECTED == 0x10
    assert LLKHF_UP == 0x80


def test_event_is_frozen():
    e = classify(**HUMAN_DOWN)
    try:
        e.vk = 1  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("KeyEvent should be immutable")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_keyevents.py -v`
Expected: collection error — no module named `keyevents`.

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/keyevents.py
"""Telling our own synthetic keystrokes from the user's hands.

Validated by spike (spec section 8): every event we generate carries SIGNATURE
in ``dwExtraInfo``, and Windows independently sets ``LLKHF_INJECTED`` on
synthetic events. Requiring *both* means another automation tool's output is
never mistaken for ours, and a page that somehow set the tag without injecting
cannot impersonate us either.

Measured, not assumed:

    tagged synthetic   vk=0x87  flags=0x10  injected=True   extra=0x54595041
    real keypress      vk=0x09  flags=0x00  injected=False  extra=0x0

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

#: "TYPA". Stamped into dwExtraInfo on every keystroke we send.
SIGNATURE = 0x54595041

LLKHF_EXTENDED = 0x01
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80


@dataclass(frozen=True)
class KeyEvent:
    """One low-level keyboard event, classified."""

    vk: int
    scan: int
    flags: int
    extra_info: int

    @property
    def injected(self) -> bool:
        """Did Windows mark this as synthetic?"""
        return bool(self.flags & LLKHF_INJECTED)

    @property
    def ours(self) -> bool:
        """Injected *and* carrying our signature -- both are required."""
        return self.injected and self.extra_info == SIGNATURE

    @property
    def human(self) -> bool:
        """Came from real hardware, so the user is typing."""
        return not self.injected

    @property
    def is_up(self) -> bool:
        return bool(self.flags & LLKHF_UP)

    @property
    def is_down(self) -> bool:
        return not self.is_up


def classify(vk: int, scan: int, flags: int, extra_info: int) -> KeyEvent:
    """Build a classified :class:`KeyEvent` from raw hook fields."""
    return KeyEvent(vk=vk, scan=scan, flags=flags, extra_info=extra_info)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_keyevents.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add typing_assistant/core/keyevents.py tests/unit/test_keyevents.py
git commit -m "feat: add injected-versus-human keystroke classification"
```

---

### Task 5: SendInput keyboard adapter

**Files:**
- Create: `typing_assistant/adapters/keyboard.py`
- Test: `tests/manual/test_keyboard_real.py`

**Interfaces:**
- Consumes: `core.keyevents.SIGNATURE`.
- Produces:
  - `SendInputKeyboard` with `send_char(ch: str) -> None`, `send_backspace() -> None`, `send_vk(vk: int, shift: bool = False) -> None`, and `unicode_fallbacks: int` counting characters the layout could not produce
  - `INPUT`, `KEYBDINPUT` ctypes structures (shared with Task 6's hook tests)

- [ ] **Step 1: Write the implementation**

`KEYEVENTF_UNICODE` is deliberately a fallback rather than the default. Unicode injection arrives as `VK_PACKET` (0xE7), so a page reading `keyCode` instead of `key` sees 231 rather than the letter. Setting both `wVk` and `wScan` without `KEYEVENTF_SCANCODE` gives a correct virtual key *and* a real scan code, which is what makes the event indistinguishable from hardware.

```python
# typing_assistant/adapters/keyboard.py
"""Sending keystrokes through SendInput, stamped so we can recognise our own.

Replaces pyautogui, which cost ~1.8 ms per call of pure overhead (spec section 8)
and resolved characters in a layout-dependent way that broke on non-US layouts.

Character resolution goes through VkKeyScanW to a real virtual key plus shift
state, with the scan code from MapVirtualKeyW. Both wVk and wScan are set and
KEYEVENTF_SCANCODE is *not* used, so consumers reading either the virtual key or
the scan code see correct values. KEYEVENTF_UNICODE is a fallback only: it
arrives as VK_PACKET (0xE7), and anything reading keyCode would see 231.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from typing_assistant.core.keyevents import SIGNATURE

_u32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

#: VkKeyScanW packs the required modifiers into the high byte.
_SHIFT_REQUIRED = 1
_CTRL_REQUIRED = 2
_ALT_REQUIRED = 4


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_u32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_u32.SendInput.restype = wintypes.UINT
_u32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
_u32.VkKeyScanW.restype = wintypes.SHORT
_u32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_u32.MapVirtualKeyW.restype = wintypes.UINT


def _key_event(vk: int, scan: int, up: bool, unicode_char: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if unicode_char:
        flags |= KEYEVENTF_UNICODE
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.ki = KEYBDINPUT(
        wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=SIGNATURE
    )
    return item


class SendInputKeyboard:
    """Types characters as though they came from the physical keyboard."""

    def __init__(self) -> None:
        self.unicode_fallbacks = 0

    # --- low level ---

    def _send(self, *events: INPUT) -> int:
        array = (INPUT * len(events))(*events)
        return _u32.SendInput(len(events), array, ctypes.sizeof(INPUT))

    def send_vk(self, vk: int, shift: bool = False) -> None:
        """Press and release *vk*, optionally with Shift held."""
        scan = _u32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        events = []
        if shift:
            shift_scan = _u32.MapVirtualKeyW(VK_SHIFT, MAPVK_VK_TO_VSC)
            events.append(_key_event(VK_SHIFT, shift_scan, up=False))
        events.append(_key_event(vk, scan, up=False))
        events.append(_key_event(vk, scan, up=True))
        if shift:
            shift_scan = _u32.MapVirtualKeyW(VK_SHIFT, MAPVK_VK_TO_VSC)
            events.append(_key_event(VK_SHIFT, shift_scan, up=True))
        self._send(*events)

    def _send_unicode(self, ch: str) -> None:
        self.unicode_fallbacks += 1
        code = ord(ch)
        self._send(
            _key_event(0, code, up=False, unicode_char=True),
            _key_event(0, code, up=True, unicode_char=True),
        )

    # --- public ---

    def send_char(self, ch: str) -> None:
        """Send one character, preferring a real virtual key over Unicode."""
        if ch == "\n" or ch == "\r":
            self.send_vk(VK_RETURN)
            return
        if ch == "\t":
            self.send_vk(VK_TAB)
            return

        scan_result = _u32.VkKeyScanW(ch)
        if scan_result == -1:
            self._send_unicode(ch)
            return

        vk = scan_result & 0xFF
        modifiers = (scan_result >> 8) & 0xFF
        if modifiers & (_CTRL_REQUIRED | _ALT_REQUIRED):
            # AltGr characters and the like: a modifier dance we do not need to
            # reproduce, and Unicode injection is correct for them.
            self._send_unicode(ch)
            return

        self.send_vk(vk, shift=bool(modifiers & _SHIFT_REQUIRED))

    def send_backspace(self) -> None:
        self.send_vk(VK_BACK)
```

- [ ] **Step 2: Write the manual verification test**

```python
# tests/manual/test_keyboard_real.py
"""Real SendInput checks. Run explicitly: pytest tests/manual -m manual -s

VK_F24 is used wherever possible so no text lands in whatever window has focus.
"""

from __future__ import annotations

import ctypes

import pytest

from typing_assistant.adapters.keyboard import INPUT, SendInputKeyboard

pytestmark = pytest.mark.manual

VK_F24 = 0x87


def test_input_struct_size_is_correct_for_this_architecture():
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(INPUT) == expected


def test_sending_an_inert_key_succeeds():
    kb = SendInputKeyboard()
    kb.send_vk(VK_F24)
    # SendInput failing returns 0 events inserted; send_vk would have raised on a
    # bad struct. Reaching here without an exception is the check.


def test_ascii_characters_need_no_unicode_fallback():
    """Every printable ASCII character must resolve to a real virtual key."""
    kb = SendInputKeyboard()
    unresolvable = []
    for code in range(0x20, 0x7F):
        ch = chr(code)
        scan_result = ctypes.WinDLL("user32").VkKeyScanW(ch)
        if scan_result == -1:
            unresolvable.append(ch)
    assert unresolvable == [], f"layout cannot produce: {unresolvable}"
    assert kb.unicode_fallbacks == 0
```

- [ ] **Step 3: Run the manual tests**

Run: `pytest tests/manual/test_keyboard_real.py -v -m manual -s`
Expected: 3 passed. If `test_ascii_characters_need_no_unicode_fallback` lists characters, the active keyboard layout cannot produce them and the Unicode fallback will be exercised — note which, as it affects Task 6's end-to-end accuracy.

- [ ] **Step 4: Confirm the default run is unaffected**

Run: `pytest`
Expected: all pass, manual tests deselected.

- [ ] **Step 5: Commit**

```bash
git add typing_assistant/adapters/keyboard.py tests/manual/test_keyboard_real.py
git commit -m "feat: add tagged SendInput keyboard backend with scan-code output"
```

---

### Task 6: Keyboard monitor, CLI, and end-to-end verification

The monitor installs the low-level hook on its own thread, classifies every event, and turns a human keypress into a pause. The CLI wires clock, keyboard, monitor, pacing and typist into something usable.

**Files:**
- Create: `typing_assistant/adapters/hotkeys.py`
- Create: `typing_assistant/adapters/store.py`
- Create: `typing_assistant/cli.py`
- Create: `typing_assistant/__main__.py`
- Test: `tests/unit/test_store.py`
- Test: `tests/manual/test_end_to_end.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `core.keyevents.classify`, `core.typist.type_schedule`, `core.pacing.schedule`, `core.pacing.PacingConfig`, `core.text.normalize`, `core.calibration.calibration_factor`, `adapters.clock.SystemClock`, `adapters.keyboard.SendInputKeyboard`.
- Produces:
  - `KeyboardMonitor(on_human=None, abort_vk=None)` with `start()`, `stop()`, `human_text: str`, `abort_requested: bool`, `pause_requested: bool`, `clear()`
  - `load_calibration() -> float`, `save_calibration(factor: float) -> None`, `config_dir() -> pathlib.Path`
  - CLI entry point `main(argv=None) -> int` with subcommands `type` and `calibrate`

- [ ] **Step 1: Write the keyboard monitor**

The hook callback has a latency budget of roughly 300 ms before Windows silently drops the hook, so it does nothing but record and return.

```python
# typing_assistant/adapters/hotkeys.py
"""Watching the keyboard so a human keypress can stop us instantly.

Runs a WH_KEYBOARD_LL hook on its own thread with a message pump, which is what
such a hook requires. The callback records and returns immediately: Windows
drops a hook whose callback exceeds roughly 300 ms.

No elevation needed -- confirmed by spike (spec section 8, finding 3).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional

from typing_assistant.core.keyevents import classify

_u32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_ssize_t

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
_HC_ACTION = 0

VK_ESCAPE = 0x1B


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_u32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)
_u32.SetWindowsHookExW.restype = wintypes.HHOOK
_u32.CallNextHookEx.argtypes = (
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_u32.CallNextHookEx.restype = LRESULT
_u32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_u32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_u32.PostThreadMessageW.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_u32.ToUnicode.argtypes = (
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_char_p,
    wintypes.LPWSTR,
    ctypes.c_int,
    wintypes.UINT,
)
_u32.ToUnicode.restype = ctypes.c_int
_u32.GetKeyboardState.argtypes = (ctypes.c_char_p,)


def _vk_to_char(vk: int, scan: int) -> Optional[str]:
    """Best-effort character for a human keypress, for resync matching."""
    state = ctypes.create_string_buffer(256)
    _u32.GetKeyboardState(state)
    buffer = ctypes.create_unicode_buffer(8)
    count = _u32.ToUnicode(vk, scan, state, buffer, len(buffer), 0)
    if count == 1:
        return buffer[0]
    return None


class KeyboardMonitor:
    """Classifies every keystroke and records what the human typed.

    ``pause_requested`` goes true the moment a real key is pressed -- the single
    mechanism that serves as panic stop, "let me take over", and resync trigger.
    ``abort_requested`` goes true for the dedicated abort key.
    """

    def __init__(
        self,
        on_human: Optional[Callable[[str], None]] = None,
        abort_vk: int = VK_ESCAPE,
    ) -> None:
        self._on_human = on_human
        self._abort_vk = abort_vk
        self._hook = None
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._human_chars: list[str] = []
        self.abort_requested = False
        self.pause_requested = False
        # Held so ctypes does not garbage-collect the live callback.
        self._proc = _HOOKPROC(self._callback)

    # --- hook plumbing ---

    def _callback(self, code, wparam, lparam):
        if code == _HC_ACTION:
            data = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            event = classify(data.vkCode, data.scanCode, data.flags, data.dwExtraInfo)
            if event.human and event.is_down:
                self.pause_requested = True
                if event.vk == self._abort_vk:
                    self.abort_requested = True
                char = _vk_to_char(event.vk, event.scan)
                if char is not None:
                    with self._lock:
                        self._human_chars.append(char)
                    if self._on_human is not None:
                        self._on_human(char)
        return _u32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self) -> None:
        self._thread_id = _u32.GetCurrentThreadId() if hasattr(_u32, "GetCurrentThreadId") else 0
        self._thread_id = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        self._hook = _u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook:
            return
        message = wintypes.MSG()
        while _u32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            pass
        _u32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    # --- public ---

    def start(self, timeout: float = 2.0) -> bool:
        """Install the hook. Returns whether it was installed successfully."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._hook is not None

    def stop(self) -> None:
        if self._thread_id:
            _u32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def human_text(self) -> str:
        with self._lock:
            return "".join(self._human_chars)

    def clear(self) -> None:
        with self._lock:
            self._human_chars.clear()
        self.abort_requested = False
        self.pause_requested = False

    def is_set(self) -> bool:
        """Adapts to core.typist's abort protocol."""
        return self.pause_requested

    def __enter__(self) -> "KeyboardMonitor":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
```

- [ ] **Step 2: Write the calibration store**

```python
# typing_assistant/adapters/store.py
"""Where the per-machine calibration factor lives.

%APPDATA%\\TypingAssistant\\, not the working directory. The old config was read
from the current directory (``main.py:21``), so running the tool from anywhere
else silently started from defaults.
"""

from __future__ import annotations

import json
import os
import pathlib

_APP_FOLDER = "TypingAssistant"
_FILENAME = "calibration.json"
_SCHEMA_VERSION = 1


def config_dir() -> pathlib.Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return pathlib.Path(base) / _APP_FOLDER


def _path() -> pathlib.Path:
    return config_dir() / _FILENAME


def load_calibration(default: float = 1.0) -> float:
    """Return the stored factor, or *default* if absent or unreadable."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    value = data.get("factor", default)
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return default
    return factor if factor > 0 else default


def save_calibration(factor: float) -> pathlib.Path:
    """Write *factor*, creating the directory if needed. Returns the path."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _path()
    path.write_text(
        json.dumps({"version": _SCHEMA_VERSION, "factor": factor}, indent=2),
        encoding="utf-8",
    )
    return path
```

- [ ] **Step 3: Write the store tests**

```python
# tests/unit/test_store.py
from __future__ import annotations

import json

from typing_assistant.adapters import store


def test_config_dir_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert store.config_dir() == tmp_path / "TypingAssistant"


def test_missing_file_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert store.load_calibration(default=1.0) == 1.0


def test_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store.save_calibration(0.87)
    assert store.load_calibration() == 0.87


def test_saved_file_is_versioned(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = store.save_calibration(0.9)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["factor"] == 0.9


def test_corrupt_file_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text("{not json", encoding="utf-8")
    assert store.load_calibration(default=1.0) == 1.0


def test_nonsense_factor_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text(
        json.dumps({"version": 1, "factor": "banana"}), encoding="utf-8"
    )
    assert store.load_calibration(default=1.0) == 1.0


def test_zero_factor_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text(
        json.dumps({"version": 1, "factor": 0}), encoding="utf-8"
    )
    assert store.load_calibration(default=1.0) == 1.0
```

- [ ] **Step 4: Run the store tests**

Run: `pytest tests/unit/test_store.py -v`
Expected: 7 passed.

- [ ] **Step 5: Write the CLI**

```python
# typing_assistant/cli.py
"""Command line entry point.

    python -m typing_assistant type --text "hello" --wpm 55
    python -m typing_assistant type --file passage.txt --wpm 45
    python -m typing_assistant calibrate --wpm 55

Arming never starts a countdown. It waits indefinitely for the go key, so there
is no timed interaction to race -- the fixed eight-second sleep at
``main.py:95`` is gone.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import sys
import time

from typing_assistant.adapters.clock import SystemClock
from typing_assistant.adapters.hotkeys import KeyboardMonitor
from typing_assistant.adapters.keyboard import SendInputKeyboard
from typing_assistant.adapters import store
from typing_assistant.core.calibration import calibration_factor, within_tolerance
from typing_assistant.core.pacing import PacingConfig, SpacingMode, schedule
from typing_assistant.core.text import normalize
from typing_assistant.core.typist import type_schedule

CALIBRATION_PASSAGE = (
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen "
    "liquor jugs. How vexingly quick daft zebras jump. Bright vixens jump for "
    "the lazy dogs and the quick brown foxes watch them go."
)


def _read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        return pathlib.Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _wait_for_go(seconds_between_checks: float = 0.05) -> None:
    """Block until the user presses Enter in this console."""
    print("Click into your target window, then press Enter here to start.")
    print("While typing: any key pauses, Escape aborts.")
    sys.stdin.readline()
    # A moment for focus to settle back on the target window.
    time.sleep(0.4)


def _run_typing(text: str, wpm: float, spacing: SpacingMode, seed: int | None) -> int:
    prepared = normalize(text)
    if not prepared:
        print("Nothing to type.", file=sys.stderr)
        return 2

    factor = store.load_calibration()
    config = PacingConfig(wpm=wpm, calibration=factor, spacing=spacing)
    rng = random.Random(seed)
    keystrokes = schedule(prepared, config, rng)

    print(f"{len(prepared)} characters at {wpm:g} WPM (calibration {factor:.3f}).")
    _wait_for_go()

    keyboard = SendInputKeyboard()
    monitor = KeyboardMonitor()
    if not monitor.start():
        print("Could not install the keyboard hook; abort would not work.", file=sys.stderr)
        return 3

    try:
        with SystemClock() as clock:
            if not clock.high_resolution:
                print("Warning: high-resolution timer unavailable; rhythm may be coarse.")
            monitor.clear()
            result = type_schedule(keystrokes, keyboard, clock, abort=monitor)
    finally:
        monitor.stop()

    print()
    print(f"Sent {len(result.sent)} of {len(prepared)} characters.")
    print(f"Measured {result.wpm:.1f} WPM in {result.elapsed:.2f}s.")
    if keyboard.unicode_fallbacks:
        print(f"{keyboard.unicode_fallbacks} character(s) needed the Unicode fallback.")
    if result.aborted:
        reason = "Escape" if monitor.abort_requested else "a keypress"
        print(f"Stopped early by {reason}.")
        typed_by_hand = monitor.human_text
        if typed_by_hand:
            print(f"You typed {len(typed_by_hand)} character(s) while it was stopped.")
        return 1
    return 0


def _run_calibration(wpm: float, rounds: int) -> int:
    print("Calibration types a known passage into this console.")
    print("Focus this window and do not touch the keyboard while it runs.\n")
    factor = store.load_calibration()
    keyboard = SendInputKeyboard()

    for round_number in range(1, rounds + 1):
        config = PacingConfig(wpm=wpm, calibration=factor)
        keystrokes = schedule(CALIBRATION_PASSAGE, config, random.Random(round_number))
        _wait_for_go()
        with SystemClock() as clock:
            result = type_schedule(keystrokes, keyboard, clock)
        print()
        print(f"Round {round_number}: asked {wpm:g}, measured {result.wpm:.1f} WPM.")
        if result.aborted:
            print("Aborted; calibration unchanged.")
            return 1
        if within_tolerance(wpm, result.wpm):
            print(f"Within tolerance. Factor {factor:.3f}.")
            break
        factor = calibration_factor(wpm, result.wpm, previous=factor)
        print(f"Adjusted factor to {factor:.3f}.")

    path = store.save_calibration(factor)
    print(f"Saved to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="typing_assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    type_parser = subparsers.add_parser("type", help="type a block of text")
    source = type_parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="text to type")
    source.add_argument("--file", help="file whose contents to type")
    type_parser.add_argument("--wpm", type=float, default=55.0)
    type_parser.add_argument(
        "--double-space",
        action="store_true",
        help="double-space after sentence-ending periods (default: reproduce the source)",
    )
    type_parser.add_argument("--seed", type=int, default=None)

    cal_parser = subparsers.add_parser("calibrate", help="measure this machine")
    cal_parser.add_argument("--wpm", type=float, default=55.0)
    cal_parser.add_argument("--rounds", type=int, default=3)

    args = parser.parse_args(argv)

    if args.command == "type":
        spacing = SpacingMode.DOUBLE if args.double_space else SpacingMode.FAITHFUL
        return _run_typing(_read_text(args), args.wpm, spacing, args.seed)
    return _run_calibration(args.wpm, args.rounds)
```

- [ ] **Step 6: Write the module entry point**

```python
# typing_assistant/__main__.py
from __future__ import annotations

import sys

from typing_assistant.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Verify the CLI parses and the pipeline assembles**

Run: `python -m typing_assistant type --help`
Expected: usage text listing `--text`, `--file`, `--wpm`, `--double-space`, `--seed`.

Run: `python -m typing_assistant calibrate --help`
Expected: usage text listing `--wpm`, `--rounds`.

- [ ] **Step 8: Write the end-to-end verification**

This is where the acceptance criteria from spec §9.6 get measured for the first time.

```python
# tests/manual/test_end_to_end.py
"""End-to-end verification against the local practice target.

    python -m http.server 8777 --directory tools/practice

Then open http://localhost:8777/, click the passage, and run:

    pytest tests/manual/test_end_to_end.py -v -m manual -s

The browser window must stay focused for the whole run -- keystrokes go to
whatever has focus.
"""

from __future__ import annotations

import random

import pytest

from typing_assistant.adapters.clock import SystemClock
from typing_assistant.adapters.keyboard import SendInputKeyboard
from typing_assistant.core.pacing import PacingConfig, schedule
from typing_assistant.core.typist import type_schedule

pytestmark = pytest.mark.manual

PASSAGE = "The quick brown fox jumps over the lazy dog."


@pytest.mark.parametrize("target_wpm", [40.0, 55.0, 70.0])
def test_measured_wpm_lands_within_tolerance(target_wpm):
    """Acceptance criterion: measured WPM within 2 of target."""
    keystrokes = schedule(PASSAGE, PacingConfig(wpm=target_wpm), random.Random(1))
    keyboard = SendInputKeyboard()
    with SystemClock() as clock:
        result = type_schedule(keystrokes, keyboard, clock)
    print(f"\ntarget {target_wpm:g} -> measured {result.wpm:.2f} WPM")
    assert abs(result.wpm - target_wpm) <= 2.0
    assert result.sent == PASSAGE
    assert keyboard.unicode_fallbacks == 0
```

- [ ] **Step 9: Run the end-to-end verification by hand**

1. Start the practice target:
   `python -m http.server 8777 --directory tools/practice`
2. Open <http://localhost:8777/> and click the passage so the hidden sink has focus.
3. In another console, run:
   `pytest tests/manual/test_end_to_end.py -v -m manual -s`
4. Check, in the browser:
   - `practice.stats().typedText` matches the passage prefix exactly
   - `practice.stats().accuracy` is 100
   - `practice.stats().wpm` is within about 2 of the target
   - `practice.log()` shows right-skewed inter-key intervals, not uniform ones

If measured WPM is outside tolerance, run `python -m typing_assistant calibrate --wpm 55` first and repeat — that is exactly what calibration exists for.

If the browser records wrong characters, the scan-code approach is not reaching it correctly; switch `_key_event` to set `KEYEVENTF_SCANCODE` with `wVk=0` and re-run. Spec §6.8 records why the current form was chosen first.

- [ ] **Step 10: Verify the panic stop by hand**

1. Run `python -m typing_assistant type --text "$(python -c "print('word ' * 200)")" --wpm 40`
2. Press Enter to start, then tap any key while it is typing.
3. Confirm it stops within one character, reports how many were sent, and reports how many you typed while stopped.
4. Repeat with Escape and confirm it reports "Stopped early by Escape".

This is the behaviour v1 never had — `main.py:64` ignored its own hotkey once typing began.

- [ ] **Step 11: Update the README**

Replace the `## Status` section with:

```markdown
## Status

**v2 typing engine is usable now.** It types text you give it, at an accurate
WPM, with a panic stop:

    python -m typing_assistant calibrate --wpm 55
    python -m typing_assistant type --text "hello there" --wpm 55
    python -m typing_assistant type --file passage.txt --wpm 45

Any keypress pauses it; Escape aborts. No Administrator needed, and no countdown
to race — it waits for you.

Reading text off the screen with OCR is not wired into v2 yet, so for that
workflow v1 (`python main.py`) is still the tool. See the
[design spec](docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md)
for what is coming and the 25-defect register it works from.

**v1 still works** and is described below, rough edges and all.
```

- [ ] **Step 12: Run the whole default suite**

Run: `pytest`
Expected: all pass, manual tests deselected.

- [ ] **Step 13: Commit**

```bash
git add typing_assistant/adapters/hotkeys.py typing_assistant/adapters/store.py typing_assistant/cli.py typing_assistant/__main__.py tests/unit/test_store.py tests/manual/test_end_to_end.py README.md
git commit -m "feat: add keyboard monitor, CLI, and end-to-end verification"
```

---

## Self-review

**Spec coverage for this plan's scope:**

| Spec section | Task |
|---|---|
| §5.1 immutable config snapshot per run | 6 (`PacingConfig` built once before arming) |
| §5.3 abort and pause, injected-vs-human | 4, 6 |
| §5.3 abort checked between every keystroke | 2 (`test_abort_stops_within_one_keystroke`) |
| §5.2 `READY` waits indefinitely, no countdown | 6 (`_wait_for_go`) |
| §6.6 schedule consumed as scheduled keystrokes | 2 |
| §6.7 calibration, closed-loop correction | 2, 3, 6 |
| §6.8 scan-code output, Unicode as fallback only | 5 |
| §6.8 high-resolution waitable timer | 1 |
| §6.9 observed human keystrokes on pause | 6 (`KeyboardMonitor.human_text`) |
| §7.4 config in `%APPDATA%`, versioned | 6 (`store.py`) |
| §7.6 no silent `print()`-only errors for the user | 6 (CLI reports outcomes) |
| §9.4 fake adapters, abort latency asserted | 1, 2 |
| §9.6 measured WPM within ±2 | 6 (`test_measured_wpm_lands_within_tolerance`) |

Deferred, with the plan that covers them:

- §6.1 capture, §6.2 OCR, §6.5 cursor driven by live OCR reads, §5.2 the full state
  machine, §9.3 golden images — **Plan 3**.
- §7.1–7.3, §7.5, §7.7, §7.8 profiles, auto-detect, region editor, Tesseract discovery,
  UI accessibility, wizard, §11 packaging — **Plan 4**.

`core.cursor.TypedCursor` is wired into the typist here (Task 2) but only exercised
against a passage known upfront. Its append-only invariant matters when live OCR reads
start extending the buffer, which is Plan 3.

**Type consistency check:** `TypeResult` field names (`sent`, `aborted`, `elapsed`,
`wpm`) match between Task 2's interface block, tests and implementation, and Task 6's
CLI use. `FakeClock`'s `now`/`sleep`/`sleeps`/`drift` match across Tasks 1, 2 and 3.
`FakeKeyboard`'s `sent`/`text`/`send_char`/`on_send` match Tasks 2 and 6.
`SendInputKeyboard.send_char`/`send_backspace`/`send_vk`/`unicode_fallbacks` match
Tasks 5 and 6. `KeyEvent`'s `vk`/`scan`/`flags`/`extra_info` and its `injected`/`ours`/
`human`/`is_up`/`is_down` properties match Tasks 4 and 6. `KeyboardMonitor.is_set()`
satisfies the abort protocol `core.typist.type_schedule` expects, so the monitor can be
passed directly as `abort`. `store.load_calibration`/`save_calibration` match Tasks 6's
tests and CLI. `calibration_factor(target, measured, previous)` argument order matches
Tasks 3 and 6.

**Placeholder scan:** none. Every code step contains complete, runnable content.

**Known rough edge, deliberately left:** `_wait_for_go` uses console Enter rather than a
global go hotkey, because a global hotkey needs the hook to distinguish its own trigger
from the pause mechanism, and that interaction deserves the state machine it gets in
Plan 3. The consequence is that the user must return focus to the console to start —
acceptable for a CLI, and it is still untimed, which is the property that matters.
