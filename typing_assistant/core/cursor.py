"""The append-only typed cursor.

Holds the authoritative record of every character actually sent. New OCR reads
may only *extend* what is known; a read that contradicts or merely repeats
already-known text is discarded as noise. That makes duplicate typing impossible
by construction rather than unlikely, replacing the difflib ``replace`` filter at
``main.py:151``.

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

#: Minimum overlap, in characters, before a scrolled read is trusted to join on.
_MIN_OVERLAP = 8


class TypedCursor:
    """Tracks the passage learned so far and how much of it has been emitted."""

    def __init__(self) -> None:
        self._known = ""
        self._emitted = 0

    # --- state ---

    @property
    def known(self) -> str:
        """Every character of the passage learned so far."""
        return self._known

    @property
    def emitted(self) -> str:
        """Every character actually sent. This string only ever grows."""
        return self._known[: self._emitted]

    @property
    def pending(self) -> str:
        """Known text not yet sent."""
        return self._known[self._emitted :]

    def reset(self) -> None:
        """Forget everything. Used when a new run is armed."""
        self._known = ""
        self._emitted = 0

    # --- learning ---

    def observe(self, read: str) -> int:
        """Merge an OCR *read* into the passage; return characters gained.

        Returns 0 and changes nothing unless *read* genuinely extends what is
        already known.
        """
        if not read:
            return 0

        if not self._known:
            self._known = read
            return len(read)

        # Growth at the front: the read is the same passage, seen further along.
        if read.startswith(self._known):
            gained = len(read) - len(self._known)
            self._known = read
            return gained

        # The read is a prefix of, or equal to, what we know: nothing new.
        if self._known.startswith(read):
            return 0

        # Scrolled window: the read's head overlaps our tail. Find the longest
        # such overlap and append only the remainder.
        limit = min(len(read), len(self._known))
        for size in range(limit, _MIN_OVERLAP - 1, -1):
            if self._known.endswith(read[:size]):
                remainder = read[size:]
                if not remainder:
                    return 0
                self._known += remainder
                return len(remainder)

        # No trustworthy relationship. Discard rather than guess; guessing is
        # what produces duplicate typing.
        return 0

    # --- emitting ---

    def take(self, count: int) -> str:
        """Mark up to *count* pending characters as emitted and return them."""
        if count <= 0:
            return ""
        chunk = self._known[self._emitted : self._emitted + count]
        self._emitted += len(chunk)
        return chunk

    def advance_matched(self, keystrokes: str) -> int:
        """Credit *keystrokes* typed by the user, stopping at the first mismatch.

        Used on resume: while paused, the keyboard hook observes what the user
        typed during manual catch-up, so the cursor can advance without re-OCR.
        """
        matched = 0
        for ch in keystrokes:
            if self._emitted + matched >= len(self._known):
                break
            if self._known[self._emitted + matched] != ch:
                break
            matched += 1
        self._emitted += matched
        return matched
