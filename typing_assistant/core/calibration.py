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
