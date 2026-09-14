"""Turning text into a timed keystroke schedule.

The schedule is normalized so its total duration is exactly what the requested
WPM implies. Rhythm shaping redistributes time inside that budget; it never adds
to it. This is what lets the WPM setting be honest without a fudge factor.

Pure module: randomness arrives as an injected ``random.Random``.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass
from typing import Sequence

#: Standard typing-test definition of a "word": five characters, spaces included.
CHARS_PER_WORD = 5

#: Lowercased, dot-terminated tokens that end in a period without ending a sentence.
ABBREVIATIONS = frozenset(
    {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "rev.", "hon.",
        "vs.", "etc.", "e.g.", "i.e.", "cf.", "al.", "ibid.", "viz.",
        "inc.", "ltd.", "co.", "corp.", "dept.", "univ.",
        "no.", "vol.", "fig.", "ed.", "pp.", "ch.",
        "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.",
        "oct.", "nov.", "dec.",
        "mon.", "tue.", "tues.", "wed.", "thu.", "thurs.", "fri.", "sat.", "sun.",
        "approx.", "est.", "min.", "max.", "avg.", "a.m.", "p.m.",
    }
)

#: Substrings that mark a whitespace-delimited token as a URL, path or address,
#: where an internal period never ends a sentence.
_NON_PROSE_MARKERS = ("://", "/", "@", "\\", "www.")


class SpacingMode(enum.Enum):
    """How to space after a sentence-ending period.

    FAITHFUL reproduces the source exactly and is the default: inserting a space
    the source does not contain is itself a scored error. DOUBLE exists for tests
    that demand typewriter convention.
    """

    FAITHFUL = "faithful"
    DOUBLE = "double"


@dataclass(frozen=True)
class PacingConfig:
    """Parameters controlling the shape and speed of typing."""

    wpm: float
    variation: float = 0.12
    word_pause: float = 1.6
    sentence_pause: float = 3.0
    calibration: float = 1.0
    spacing: SpacingMode = SpacingMode.FAITHFUL

    def __post_init__(self) -> None:
        if self.wpm <= 0:
            raise ValueError("wpm must be positive")
        if self.variation < 0:
            raise ValueError("variation must not be negative")
        if self.calibration <= 0:
            raise ValueError("calibration must be positive")
        if self.word_pause < 1.0 or self.sentence_pause < 1.0:
            raise ValueError("pause factors must be at least 1.0")


@dataclass(frozen=True)
class Keystroke:
    """One character and the delay to wait *before* sending it."""

    char: str
    delay: float


def _token_bounds(text: str, index: int) -> tuple[int, int]:
    """Return the whitespace-delimited token containing *index*."""
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = index
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def is_sentence_end(text: str, index: int) -> bool:
    """Is the period at *index* the end of a sentence?

    False for abbreviations, decimals, URLs, paths and email addresses, and when
    the following word is not capitalised.
    """
    if index < 0 or index >= len(text) or text[index] != ".":
        return False

    # A digit immediately after means a decimal, e.g. "3.14".
    if index + 1 < len(text) and text[index + 1].isdigit():
        return False

    start, end = _token_bounds(text, index)
    token = text[start:end]
    if any(marker in token for marker in _NON_PROSE_MARKERS):
        return False

    # The token up to and including this period, e.g. "Mr." or "e.g.".
    prefix = text[start : index + 1].lower()
    if prefix in ABBREVIATIONS:
        return False

    # End of input counts as a sentence end.
    rest = text[index + 1 :]
    if not rest.strip():
        return True

    # Otherwise the next non-space character must start a new sentence.
    if not rest[:1].isspace():
        return False
    stripped = rest.lstrip()
    first = stripped[0]
    return first.isupper() or first.isdigit() or first in "\"'"


def apply_spacing(text: str, mode: SpacingMode) -> str:
    """Return *text* with sentence spacing adjusted per *mode*."""
    if mode is SpacingMode.FAITHFUL:
        return text

    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        out.append(ch)
        if ch == "." and is_sentence_end(text, i):
            # Exactly one following space becomes two; leave anything else alone.
            if text[i + 1 : i + 2] == " " and text[i + 2 : i + 3] != " ":
                out.append("  ")
                i += 2
                continue
        i += 1
    return "".join(out)


def target_duration(char_count: int, wpm: float) -> float:
    """Seconds that *char_count* characters should take at *wpm*."""
    if wpm <= 0:
        raise ValueError("wpm must be positive")
    return (char_count / CHARS_PER_WORD) / wpm * 60.0


def measured_wpm(char_count: int, seconds: float) -> float:
    """Gross WPM implied by typing *char_count* characters in *seconds*."""
    if seconds <= 0:
        return 0.0
    return (char_count / CHARS_PER_WORD) / (seconds / 60.0)


def _jitter(rng: random.Random, variation: float) -> float:
    """A positive multiplier with mean ~1 and a right-skewed tail.

    Human inter-key intervals are lognormal-ish: mostly tight, occasionally long.
    A symmetric uniform draw (as in main.py:193) reads as machine-generated.
    """
    if variation <= 0:
        return 1.0
    sigma = variation
    mu = -(sigma ** 2) / 2.0  # so that exp(mu + sigma^2/2) == 1
    return min(3.0, max(0.35, rng.lognormvariate(mu, sigma)))


def _weights(text: str, config: PacingConfig, rng: random.Random) -> list[float]:
    """Relative time weight for each character, before normalization."""
    weights = []
    for i, ch in enumerate(text):
        weight = _jitter(rng, config.variation)
        if ch.isspace():
            previous = text[i - 1] if i > 0 else ""
            if previous == "." and is_sentence_end(text, i - 1):
                weight *= config.sentence_pause
            elif previous in "!?":
                weight *= config.sentence_pause
            else:
                weight *= config.word_pause
        weights.append(weight)
    return weights


def schedule(
    text: str, config: PacingConfig, rng: random.Random
) -> tuple[Keystroke, ...]:
    """Return a keystroke schedule whose total duration matches ``config.wpm``.

    ``config.calibration`` scales the whole schedule to correct for a machine's
    measured deviation; 1.0 means no correction.
    """
    prepared = apply_spacing(text, config.spacing)
    if not prepared:
        return ()

    weights = _weights(prepared, config, rng)
    total_weight = math.fsum(weights)
    budget = target_duration(len(prepared), config.wpm) * config.calibration
    scale = budget / total_weight

    return tuple(
        Keystroke(char=ch, delay=weight * scale)
        for ch, weight in zip(prepared, weights)
    )


def total_duration(keystrokes: Sequence[Keystroke]) -> float:
    """Total scheduled time for *keystrokes*."""
    return math.fsum(k.delay for k in keystrokes)
