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
