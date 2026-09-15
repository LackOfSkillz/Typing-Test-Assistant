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
