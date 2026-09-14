"""Normalization of OCR output into text a keyboard can reproduce exactly.

Pure module: no I/O, no randomness. See the plan's Global Constraints.
"""

from __future__ import annotations

import re

#: Characters OCR commonly returns that no keyboard key produces directly.
#: Every value must be ASCII so the keyboard adapter can always send it.
NORMALIZATION_MAP = {
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "„": '"',   # low double quote
    "‘": "'",   # left single quote
    "’": "'",   # right single quote / apostrophe
    "‚": "'",   # low single quote
    "′": "'",   # prime
    "″": '"',   # double prime
    "—": "-",   # em dash
    "–": "-",   # en dash
    "−": "-",   # minus sign
    "…": "...",  # ellipsis
    " ": " ",   # non-breaking space
    " ": " ",   # en space
    " ": " ",   # em space
    " ": " ",   # thin space
    "​": "",    # zero-width space
    "﻿": "",    # byte-order mark
}

_TRANSLATION = {ord(src): dst for src, dst in NORMALIZATION_MAP.items()}

_HORIZONTAL_WS = re.compile(r"[ \t\f\v]+")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_LEADING_WS = re.compile(r"^[ \t]+", re.MULTILINE)
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize(raw: str) -> str:
    """Return *raw* with unreproducible characters mapped and whitespace tidied.

    Paragraph structure is preserved: a single newline stays a newline, a blank
    line stays a blank line. Runs of three or more newlines collapse to two.
    Horizontal whitespace runs collapse to a single space.
    """
    if not raw:
        return ""

    text = raw.translate(_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _TRAILING_WS.sub("", text)
    text = _LEADING_WS.sub("", text)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()
