from __future__ import annotations

from typing_assistant.core.cursor import TypedCursor


def test_starts_empty():
    c = TypedCursor()
    assert c.known == ""
    assert c.emitted == ""
    assert c.pending == ""


def test_first_observation_becomes_the_passage():
    c = TypedCursor()
    gained = c.observe("hello world")
    assert gained == 11
    assert c.known == "hello world"
    assert c.pending == "hello world"


def test_take_moves_text_from_pending_to_emitted():
    c = TypedCursor()
    c.observe("hello world")
    assert c.take(5) == "hello"
    assert c.emitted == "hello"
    assert c.pending == " world"


def test_take_more_than_pending_returns_what_exists():
    c = TypedCursor()
    c.observe("abc")
    assert c.take(99) == "abc"
    assert c.pending == ""


def test_take_zero_or_negative_is_a_noop():
    c = TypedCursor()
    c.observe("abc")
    assert c.take(0) == ""
    assert c.take(-3) == ""
    assert c.emitted == ""


def test_repeated_identical_read_gains_nothing():
    c = TypedCursor()
    c.observe("hello world")
    assert c.observe("hello world") == 0
    assert c.known == "hello world"


def test_extension_by_prefix_growth():
    c = TypedCursor()
    c.observe("the quick brown")
    gained = c.observe("the quick brown fox jumps")
    assert gained == 10
    assert c.known == "the quick brown fox jumps"


def test_scrolled_read_overlapping_the_tail_extends():
    # The window scrolled: the new read starts mid-passage.
    c = TypedCursor()
    c.observe("alpha beta gamma")
    gained = c.observe("beta gamma delta")
    assert gained == 6
    assert c.known == "alpha beta gamma delta"


def test_truncated_read_is_discarded():
    c = TypedCursor()
    c.observe("alpha beta gamma")
    assert c.observe("alpha beta") == 0
    assert c.known == "alpha beta gamma"


def test_read_contradicting_emitted_text_is_discarded():
    # This is the retype bug. OCR flickers on already-typed text; ignore it.
    c = TypedCursor()
    c.observe("alpha beta gamma")
    c.take(10)  # emitted "alpha beta"
    assert c.observe("alpha bela gamma delta") == 0
    assert c.emitted == "alpha beta"
    assert "bela" not in c.known


def test_unrelated_read_is_discarded():
    c = TypedCursor()
    c.observe("alpha beta")
    assert c.observe("completely different text") == 0
    assert c.known == "alpha beta"


def test_emitted_never_shrinks_across_observations():
    c = TypedCursor()
    c.observe("one two three")
    c.take(7)
    before = c.emitted
    for read in ("one two", "xxx", "", "one two three four"):
        c.observe(read)
        assert c.emitted == before


def test_empty_read_is_a_noop():
    c = TypedCursor()
    c.observe("abc")
    assert c.observe("") == 0


def test_advance_matched_credits_human_keystrokes():
    c = TypedCursor()
    c.observe("hello world")
    c.take(6)  # emitted "hello "
    matched = c.advance_matched("wor")
    assert matched == 3
    assert c.emitted == "hello wor"
    assert c.pending == "ld"


def test_advance_matched_stops_at_the_first_mismatch():
    c = TypedCursor()
    c.observe("hello world")
    c.take(6)
    assert c.advance_matched("wXr") == 1
    assert c.emitted == "hello w"


def test_advance_matched_with_no_match_changes_nothing():
    c = TypedCursor()
    c.observe("hello")
    assert c.advance_matched("zzz") == 0
    assert c.emitted == ""


def test_reset_clears_everything():
    c = TypedCursor()
    c.observe("abc")
    c.take(2)
    c.reset()
    assert (c.known, c.emitted, c.pending) == ("", "", "")


def test_known_always_starts_with_emitted():
    c = TypedCursor()
    for read in ("alpha beta", "beta gamma", "gamma delta epsilon"):
        c.observe(read)
        c.take(4)
        assert c.known.startswith(c.emitted)
