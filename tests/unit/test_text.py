from __future__ import annotations

import pytest

from typing_assistant.core.text import NORMALIZATION_MAP, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("“hello”", '"hello"'),
        ("‘hi’", "'hi'"),
        ("a—b", "a-b"),
        ("a–b", "a-b"),
        ("wait…", "wait..."),
        ("café", "café"),
        ("a b", "a b"),
    ],
)
def test_unicode_punctuation_is_mapped(raw, expected):
    assert normalize(raw) == expected


def test_runs_of_spaces_collapse_fully():
    # main.py:123 used replace("  ", " "), which turns three spaces into two.
    assert normalize("a   b") == "a b"
    assert normalize("a       b") == "a b"


def test_tabs_become_spaces():
    assert normalize("a\tb") == "a b"


def test_single_newline_is_preserved():
    assert normalize("line one\nline two") == "line one\nline two"


def test_paragraph_break_is_preserved():
    assert normalize("para one\n\npara two") == "para one\n\npara two"


def test_three_or_more_newlines_collapse_to_two():
    assert normalize("a\n\n\n\nb") == "a\n\nb"


def test_crlf_is_normalized():
    assert normalize("a\r\nb") == "a\nb"


def test_trailing_whitespace_per_line_is_stripped():
    assert normalize("a   \nb  ") == "a\nb"


def test_leading_and_trailing_whitespace_is_stripped():
    assert normalize("   hello   ") == "hello"


def test_empty_input():
    assert normalize("") == ""
    assert normalize("   \n  \n ") == ""


def test_normalization_map_values_are_ascii():
    for src, dst in NORMALIZATION_MAP.items():
        assert dst.isascii(), f"{src!r} maps to non-ascii {dst!r}"
