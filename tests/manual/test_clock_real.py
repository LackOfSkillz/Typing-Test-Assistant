"""Real-clock checks. Run explicitly: pytest tests/manual -m manual -s

Measured on Windows 11, and worth recording because it corrects an assumption:
the system timer resolution was *already* 1.000 ms, not the 15.625 ms often
quoted as Windows' default. Some other process on the machine had raised it.

    timer resolution: current=1.000 ms  min=0.500 ms  max=15.625 ms
    target  5.0 ms | waitable median 5.52 | time.sleep median 5.16

So on a machine in that state the waitable timer is no faster than time.sleep.
The reason to use it anyway is that 15.625 ms is the *coarsest* value, which is
what applies when nothing has raised the resolution -- and whether anything has
is entirely outside our control. The waitable timer is fine-grained regardless,
so rhythm does not silently degrade depending on what else the user is running.

These tests therefore assert absolute accuracy rather than a comparison, because
a comparison only shows a difference on a machine we cannot arrange to have.
"""

from __future__ import annotations

import ctypes
import statistics
import time

import pytest

from typing_assistant.adapters.clock import SystemClock

pytestmark = pytest.mark.manual

#: Slack above the requested duration. Covers scheduler latency on a busy box.
_TOLERANCE = 0.004


def _system_timer_resolution_ms() -> tuple[float, float, float]:
    """Return (current, minimum, maximum) timer resolution in milliseconds."""
    ntdll = ctypes.WinDLL("ntdll")
    current = ctypes.c_ulong()
    minimum = ctypes.c_ulong()
    maximum = ctypes.c_ulong()
    ntdll.NtQueryTimerResolution(
        ctypes.byref(maximum), ctypes.byref(minimum), ctypes.byref(current)
    )
    return current.value / 10000, minimum.value / 10000, maximum.value / 10000


def test_high_resolution_timer_is_available():
    with SystemClock() as clock:
        assert clock.high_resolution, "needs Windows 10 1803+"


@pytest.mark.parametrize("target", [0.002, 0.005, 0.015, 0.050])
def test_sleep_is_accurate_in_absolute_terms(target):
    """The property we actually depend on: asked for t, got about t."""
    with SystemClock() as clock:
        samples = []
        for _ in range(20):
            start = clock.now()
            clock.sleep(target)
            samples.append(clock.now() - start)

    median = statistics.median(samples)
    print(f"\n  target {target * 1000:5.1f} ms -> median {median * 1000:5.2f} ms")
    assert median >= target * 0.9, "must not undershoot"
    assert median <= target + _TOLERANCE, (
        f"median {median * 1000:.2f} ms exceeds {(target + _TOLERANCE) * 1000:.2f} ms"
    )


def test_sleep_is_not_quantised_to_the_coarse_default():
    """Consecutive short sleeps must not all land on a 15.6 ms boundary.

    This is the failure mode the waitable timer exists to prevent. It only
    actually bites when no process has raised the global resolution, so on a
    machine already running at 1 ms this passes either way -- it is a guard
    against regression, not a demonstration.
    """
    with SystemClock() as clock:
        samples = [0.0] * 10
        for i in range(10):
            start = clock.now()
            clock.sleep(0.003)
            samples[i] = clock.now() - start

    assert statistics.median(samples) < 0.010


def test_records_timer_resolution_and_comparison():
    """Informational: always passes, prints the numbers behind the docstring."""
    current, minimum, maximum = _system_timer_resolution_ms()
    print(
        f"\n  system timer resolution: current={current:.3f} ms "
        f"min={minimum:.3f} ms max={maximum:.3f} ms"
    )
    if current > 5.0:
        print("  -> coarse resolution in effect; the waitable timer is doing real work")
    else:
        print(
            "  -> another process has already raised resolution, so time.sleep "
            "would also be accurate right now"
        )

    with SystemClock() as clock:
        for target in (0.005, 0.015):
            waitable = statistics.median(
                [_elapsed(clock.sleep, target) for _ in range(20)]
            )
            builtin = statistics.median([_elapsed(time.sleep, target) for _ in range(20)])
            print(
                f"  target {target * 1000:5.1f} ms | waitable {waitable * 1000:6.2f} ms "
                f"| time.sleep {builtin * 1000:6.2f} ms"
            )


def _elapsed(sleeper, seconds: float) -> float:
    start = time.perf_counter()
    sleeper(seconds)
    return time.perf_counter() - start
