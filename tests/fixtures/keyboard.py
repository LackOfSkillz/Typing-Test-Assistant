"""Records what would have been typed, instead of typing it."""

from __future__ import annotations

from typing import Callable, Optional


class FakeKeyboard:
    """Captures every character. ``on_send`` fires after each one.

    The callback is how tests trigger an abort partway through a run, which is
    what proves the abort check happens between keystrokes.
    """

    def __init__(self, on_send: Optional[Callable[[int, str], None]] = None) -> None:
        self.sent: list[str] = []
        self.backspaces = 0
        self._on_send = on_send

    @property
    def text(self) -> str:
        return "".join(self.sent)

    def send_char(self, ch: str) -> None:
        self.sent.append(ch)
        if self._on_send is not None:
            self._on_send(len(self.sent), ch)

    def send_backspace(self) -> None:
        self.backspaces += 1
        if self.sent:
            self.sent.pop()
