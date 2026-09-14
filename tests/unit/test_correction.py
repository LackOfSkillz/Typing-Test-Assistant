from __future__ import annotations

import pytest

from typing_assistant.core.correction import (
    DEFAULT_THRESHOLD,
    Correction,
    Word,
    candidates_for,
    correct_word,
    correct_words,
    render,
    unresolved,
)

DICT = frozenset({"modern", "warning", "hello", "world", "instance", "dinner", "climb"})


# --- candidate generation ---

def test_candidates_include_the_original():
    assert "modem" in candidates_for("modem")


def test_rn_to_m_confusion():
    assert "modern" in candidates_for("modem")


def test_m_to_rn_confusion():
    assert "modem" in candidates_for("modern")


def test_l_one_i_confusion():
    cands = candidates_for("c1imb")
    assert "climb" in cands


def test_zero_o_confusion():
    assert "world" in candidates_for("w0rld")


def test_cl_d_confusion():
    assert "dinner" in candidates_for("clinner")


def test_candidates_are_unique():
    cands = candidates_for("aaa")
    assert len(cands) == len(set(cands))


def test_candidate_generation_is_bounded():
    # Guard against combinatorial explosion on a long token.
    assert len(candidates_for("rnrnrnrnrnrnrnrn")) <= 256


# --- high confidence must never be touched ---

def test_high_confidence_word_passes_through_untouched():
    word = Word("Kowalczyk", 97.0)
    result = correct_word(word, DICT)
    assert result.corrected == "Kowalczyk"
    assert result.resolved is True


def test_high_confidence_word_not_in_dictionary_is_still_kept():
    # A proper noun must not be "fixed" into something in the dictionary.
    result = correct_word(Word("modem", 99.0), DICT)
    assert result.corrected == "modem"
    assert result.resolved is True


# --- low confidence repair ---

def test_low_confidence_word_in_dictionary_is_kept():
    result = correct_word(Word("hello", 20.0), DICT)
    assert result.corrected == "hello"
    assert result.resolved is True


def test_low_confidence_word_with_one_dictionary_candidate_is_corrected():
    result = correct_word(Word("modem", 30.0), DICT)
    assert result.corrected == "modern"
    assert result.resolved is True


def test_low_confidence_word_with_no_candidate_is_unresolved():
    result = correct_word(Word("zzqqx", 10.0), DICT)
    assert result.resolved is False
    assert result.corrected == "zzqqx"
    assert "zzqqx" in result.candidates


def test_unresolved_word_offers_candidates_for_the_prompt():
    result = correct_word(Word("w0rld", 10.0), frozenset({"world", "would"}))
    assert result.resolved is True
    assert result.corrected == "world"


def test_ambiguous_candidates_are_unresolved_with_all_options():
    # Both "dinner" and "clinner" plausible -> ask rather than guess.
    result = correct_word(Word("clinner", 15.0), frozenset({"dinner", "clinner"}))
    assert result.resolved is False
    assert set(result.candidates) >= {"dinner", "clinner"}


# --- punctuation and casing are preserved ---

def test_trailing_punctuation_is_preserved_through_correction():
    result = correct_word(Word("modem.", 30.0), DICT)
    assert result.corrected == "modern."


def test_leading_punctuation_is_preserved():
    result = correct_word(Word('"modem', 30.0), DICT)
    assert result.corrected == '"modern'


def test_capitalisation_is_preserved():
    result = correct_word(Word("Modem", 30.0), DICT)
    assert result.corrected == "Modern"


def test_pure_punctuation_token_is_left_alone():
    result = correct_word(Word("--", 5.0), DICT)
    assert result.corrected == "--"
    assert result.resolved is True


def test_numeric_token_is_never_corrected():
    # "1024" must not become "l024" via the l/1 confusion pair.
    result = correct_word(Word("1024", 20.0), DICT)
    assert result.corrected == "1024"
    assert result.resolved is True


# --- sequences ---

def test_correct_words_returns_one_correction_per_word():
    words = [Word("hello", 95.0), Word("modem", 20.0)]
    results = correct_words(words, DICT)
    assert len(results) == 2
    assert results[1].corrected == "modern"


def test_unresolved_reports_indices():
    words = [Word("hello", 95.0), Word("zzqqx", 5.0), Word("world", 95.0)]
    results = correct_words(words, DICT)
    assert unresolved(results) == (1,)


def test_render_joins_with_single_spaces():
    words = [Word("hello", 95.0), Word("modem", 20.0)]
    assert render(correct_words(words, DICT)) == "hello modern"


def test_threshold_default():
    assert DEFAULT_THRESHOLD == 70.0


def test_empty_sequence():
    assert correct_words([], DICT) == ()
    assert render(()) == ""


def test_correction_is_frozen():
    c = Correction("a", "a", ("a",), True)
    with pytest.raises(Exception):
        c.corrected = "b"  # type: ignore[misc]
