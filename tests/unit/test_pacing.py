from __future__ import annotations

import random

import pytest

from typing_assistant.core.pacing import (
    CHARS_PER_WORD,
    Keystroke,
    PacingConfig,
    SpacingMode,
    apply_spacing,
    is_sentence_end,
    measured_wpm,
    schedule,
    target_duration,
    total_duration,
)


# --- sentence-ending detection: the table that main.py:190 fails ---

@pytest.mark.parametrize(
    "text,index,expected",
    [
        ("End. Next", 3, True),          # genuine sentence end
        ("Mr. Smith", 2, False),         # title abbreviation
        ("Dr. Jones", 2, False),
        ("e.g. this", 3, False),         # multi-dot abbreviation
        ("i.e. that", 3, False),
        ("etc. Then", 3, False),
        ("3.14 is pi", 1, False),        # decimal number
        ("https://x.com/a.b end", 15, False),  # inside a URL
        ("a.b@example.com x", 1, False),       # inside an email
        ("Done.", 4, True),              # end of input
        ("word. lower", 4, False),       # next word not capitalised
        ("Wait.  Two", 4, True),         # already double-spaced
    ],
)
def test_is_sentence_end(text, index, expected):
    assert text[index] == ".", "test fixture must point at a period"
    assert is_sentence_end(text, index) is expected


# --- spacing modes ---

def test_faithful_spacing_changes_nothing():
    # The source text is the ground truth; inserting a space it lacks is an error.
    text = "End. Next. Mr. Smith paid 3.14."
    assert apply_spacing(text, SpacingMode.FAITHFUL) == text


def test_double_spacing_only_at_sentence_ends():
    assert apply_spacing("End. Next", SpacingMode.DOUBLE) == "End.  Next"
    assert apply_spacing("Mr. Smith", SpacingMode.DOUBLE) == "Mr. Smith"
    assert apply_spacing("3.14 ok", SpacingMode.DOUBLE) == "3.14 ok"


def test_double_spacing_does_not_stack():
    assert apply_spacing("End.  Next", SpacingMode.DOUBLE) == "End.  Next"


# --- WPM arithmetic ---

def test_target_duration_uses_five_chars_per_word():
    assert CHARS_PER_WORD == 5
    # 300 characters at 60 WPM == 60 words == 60 seconds.
    assert target_duration(300, 60.0) == pytest.approx(60.0)


def test_measured_wpm_is_the_inverse_of_target_duration():
    assert measured_wpm(300, 60.0) == pytest.approx(60.0)
    assert measured_wpm(275, 60.0) == pytest.approx(55.0)


def test_target_duration_rejects_non_positive_wpm():
    with pytest.raises(ValueError):
        target_duration(100, 0)


# --- the schedule ---

def _cfg(**kw):
    base = dict(wpm=55.0)
    base.update(kw)
    return PacingConfig(**base)


def test_schedule_covers_every_character():
    text = "hello world"
    ks = schedule(text, _cfg(), random.Random(1))
    assert "".join(k.char for k in ks) == text


def test_spaces_are_scheduled_keystrokes():
    # main.py:199 pressed space with no sleep, inflating real WPM ~17%.
    ks = schedule("a b", _cfg(), random.Random(1))
    space = [k for k in ks if k.char == " "]
    assert len(space) == 1
    assert space[0].delay > 0


def test_total_duration_matches_the_requested_wpm():
    text = "The quick brown fox jumps over the lazy dog. " * 4
    cfg = _cfg(wpm=55.0)
    ks = schedule(text, cfg, random.Random(7))
    assert total_duration(ks) == pytest.approx(target_duration(len(text), 55.0))


def test_measured_wpm_of_the_schedule_equals_target():
    text = "The quick brown fox jumps over the lazy dog. " * 4
    ks = schedule(text, _cfg(wpm=42.0), random.Random(3))
    got = measured_wpm(len(ks), total_duration(ks))
    assert got == pytest.approx(42.0)


def test_calibration_scales_duration():
    text = "hello world this is a sentence"
    fast = schedule(text, _cfg(calibration=0.5), random.Random(5))
    slow = schedule(text, _cfg(calibration=1.0), random.Random(5))
    assert total_duration(fast) == pytest.approx(total_duration(slow) * 0.5)


def test_schedule_is_deterministic_for_a_seed():
    text = "deterministic output please"
    a = schedule(text, _cfg(), random.Random(99))
    b = schedule(text, _cfg(), random.Random(99))
    assert a == b


def test_different_seeds_give_different_rhythm():
    text = "some text long enough to vary"
    a = schedule(text, _cfg(), random.Random(1))
    b = schedule(text, _cfg(), random.Random(2))
    assert a != b


def test_zero_variation_still_shapes_pauses_but_is_repeatable():
    text = "one two. three"
    a = schedule(text, _cfg(variation=0.0), random.Random(1))
    b = schedule(text, _cfg(variation=0.0), random.Random(2))
    assert a == b, "with no jitter the schedule must not depend on the rng"


def test_word_boundary_pauses_are_longer_than_letters():
    text = "alpha beta gamma delta"
    ks = schedule(text, _cfg(variation=0.0, word_pause=2.0), random.Random(1))
    spaces = [k.delay for k in ks if k.char == " "]
    letters = [k.delay for k in ks if k.char.isalpha()]
    assert min(spaces) > max(letters)


def test_sentence_pause_is_longer_than_word_pause():
    # The next word must be capitalised, or this is correctly not a sentence end.
    text = "one two. Three four"
    ks = schedule(
        text, _cfg(variation=0.0, word_pause=1.5, sentence_pause=4.0), random.Random(1)
    )
    delays = {i: k.delay for i, k in enumerate(ks)}
    space_after_period = next(
        i for i, k in enumerate(ks) if k.char == " " and ks[i - 1].char == "."
    )
    plain_space = next(
        i for i, k in enumerate(ks)
        if k.char == " " and ks[i - 1].char != "." and i != space_after_period
    )
    assert delays[space_after_period] > delays[plain_space]


def test_all_delays_are_positive():
    text = "The quick brown fox. Jumps over! Really? Yes."
    ks = schedule(text, _cfg(), random.Random(11))
    assert all(k.delay > 0 for k in ks)


def test_empty_text_gives_empty_schedule():
    assert schedule("", _cfg(), random.Random(1)) == ()
    assert total_duration(()) == 0.0


def test_keystroke_is_frozen():
    k = Keystroke("a", 0.1)
    with pytest.raises(Exception):
        k.char = "b"  # type: ignore[misc]
