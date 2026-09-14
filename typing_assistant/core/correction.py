"""Repairing low-confidence OCR words without corrupting correct ones.

The dictionary is a source of suggestions, never an authority. A word OCR read
confidently is returned unchanged even when the dictionary does not contain it,
because proper nouns are common and a wrong "fix" is worse than the original.

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Container, Iterable, Sequence

#: Confidence below which a word is a candidate for repair. Tesseract reports 0-100.
DEFAULT_THRESHOLD = 70.0

#: Bidirectional substitutions Tesseract actually makes on screen-resolution text.
CONFUSION_PAIRS = (
    ("rn", "m"),
    ("m", "rn"),
    ("cl", "d"),
    ("d", "cl"),
    ("l", "1"),
    ("1", "l"),
    ("l", "I"),
    ("I", "l"),
    ("1", "I"),
    ("I", "1"),
    ("0", "O"),
    ("O", "0"),
    ("0", "o"),
    ("o", "0"),
    ("vv", "w"),
    ("w", "vv"),
)

#: Hard ceiling on generated candidates, so a pathological token cannot explode.
_MAX_CANDIDATES = 256

#: Characters that can appear in a wholly numeric token, e.g. "3.14", "1,024".
_NUMERIC_CHARS = set("0123456789.,:-/")

_PUNCTUATION = set(string.punctuation) | {"—", "–"}


@dataclass(frozen=True)
class Word:
    """One OCR word with the confidence the engine reported for it."""

    text: str
    confidence: float


@dataclass(frozen=True)
class Correction:
    """The outcome of considering one word.

    ``resolved`` is True when the result can be used without asking the user.
    ``candidates`` is what to offer them when it is False.
    """

    original: str
    corrected: str
    candidates: tuple[str, ...]
    resolved: bool


def _split_affixes(token: str) -> tuple[str, str, str]:
    """Split *token* into leading punctuation, core, trailing punctuation."""
    start = 0
    while start < len(token) and token[start] in _PUNCTUATION:
        start += 1
    end = len(token)
    while end > start and token[end - 1] in _PUNCTUATION:
        end -= 1
    return token[:start], token[start:end], token[end:]


def candidates_for(word: str) -> tuple[str, ...]:
    """Return *word* plus plausible confusion-pair variants, original first."""
    seen = [word]
    known = {word}

    # One substitution at a time, applied at every occurrence individually.
    frontier = [word]
    for _ in range(2):  # two passes catches e.g. "rn" plus a digit confusion
        next_frontier = []
        for current in frontier:
            for src, dst in CONFUSION_PAIRS:
                start = 0
                while True:
                    at = current.find(src, start)
                    if at < 0:
                        break
                    variant = current[:at] + dst + current[at + len(src) :]
                    if variant not in known:
                        known.add(variant)
                        seen.append(variant)
                        next_frontier.append(variant)
                        if len(seen) >= _MAX_CANDIDATES:
                            return tuple(seen)
                    start = at + 1
        frontier = next_frontier
        if not frontier:
            break
    return tuple(seen)


def _is_numeric(token: str) -> bool:
    """Is *token* wholly a number, allowing separators like ``3.14`` or ``1,024``?"""
    return bool(token) and all(ch in _NUMERIC_CHARS for ch in token) and any(
        ch.isdigit() for ch in token
    )


def _match_case(source: str, target: str) -> str:
    """Give *target* the capitalisation pattern of *source*."""
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def correct_word(
    word: Word,
    dictionary: Container[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> Correction:
    """Consider one OCR word and decide whether to repair, keep, or ask.

    *dictionary* is looked up case-insensitively and is expected to hold
    lowercase entries.
    """
    original = word.text

    def keep() -> Correction:
        return Correction(original, original, (original,), True)

    if word.confidence >= threshold:
        return keep()

    leading, core, trailing = _split_affixes(original)
    if not core:
        return keep()  # pure punctuation
    if _is_numeric(core):
        # Protects "1024" and "3.14" from the l/1 and O/0 pairs. Deliberately
        # not "contains a digit": a digit substituted inside a word ("w0rld")
        # is the most common OCR error of all, and must stay correctable.
        return keep()

    # Every dictionary-valid reading, including the word OCR actually produced.
    # Deliberately no early return when *core* is itself a dictionary word: a
    # low-confidence word that happens to be real is the dangerous case. Source
    # "modern" misread as "modem" yields two valid readings, and silently keeping
    # the misread one types the wrong word with no chance to catch it.
    #
    # Hits are keyed by canonical lowercase form, because candidate generation
    # produces case variants ("hello" also yields "hellO") and counting those as
    # separate dictionary hits would invent ambiguity that is not there. The
    # canonical form is also the right value to carry, since _match_case
    # re-applies the source word's own capitalisation below.
    hits = []
    for candidate in candidates_for(core):
        key = candidate.lower()
        if key in dictionary and key not in hits:
            hits.append(key)

    if not hits:
        return Correction(original, original, (original,), False)

    if len(hits) == 1:
        fixed = leading + _match_case(core, hits[0]) + trailing
        if fixed == original:
            return keep()
        return Correction(original, fixed, (fixed, original), True)

    # Two or more valid readings is genuine ambiguity: ask rather than guess.
    # The original leads, since it is what was actually on screen.
    options = [original]
    for hit in hits:
        option = leading + _match_case(core, hit) + trailing
        if option not in options:
            options.append(option)
    return Correction(original, original, tuple(options), False)


def correct_words(
    words: Iterable[Word],
    dictionary: Container[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[Correction, ...]:
    """Apply :func:`correct_word` across a sequence."""
    return tuple(correct_word(w, dictionary, threshold) for w in words)


def unresolved(corrections: Sequence[Correction]) -> tuple[int, ...]:
    """Indices of corrections that still need a human decision."""
    return tuple(i for i, c in enumerate(corrections) if not c.resolved)


def render(corrections: Sequence[Correction]) -> str:
    """Join corrected words into a single space-separated string."""
    return " ".join(c.corrected for c in corrections)
