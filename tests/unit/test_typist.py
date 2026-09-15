from __future__ import annotations

import random
import threading

import pytest

from tests.fixtures.clock import FakeClock
from tests.fixtures.keyboard import FakeKeyboard
from typing_assistant.core.cursor import TypedCursor
from typing_assistant.core.pacing import (
    PacingConfig,
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


def test_abort_during_a_sleep_sends_at_most_one_more_character():
    """The real scenario: a key is pressed while the typist is waiting.

    States the latency bound precisely. The abort check sits at the top of each
    iteration, before that iteration's sleep and send, so a flag raised during
    the wait before character N still lets character N through -- and nothing
    after it. One character, never two.

    Note this test does *not* discriminate checking the flag before the send
    from checking it after; mutation testing showed both yield the same count
    here. ``test_abort_set_before_starting_sends_nothing`` is the case that
    actually pins the ordering down.
    """
    abort = threading.Event()
    # Sleep #10 is the wait immediately before character 10.
    clock = FakeClock(on_sleep=lambda n, seconds: abort.set() if n == 10 else None)
    kb = FakeKeyboard()
    result = type_schedule(_schedule(), kb, clock, abort=abort)

    assert len(kb.sent) == 10, (
        "the in-flight character completes; no further character may be sent"
    )
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
#
# Thresholds below are measured, not guessed. Simulated against the real
# core.pacing schedule with correction_interval=8 and the 0.75-1.25 clamp:
#
#     drift 0.90 -> 1.63% error      drift 1.10 -> 0.69%
#     drift 1.20 -> 3.99%            drift 1.50 -> 21.8% (clamp-limited)
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
    """No requested delay may differ from its planned value beyond the clamp."""
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
