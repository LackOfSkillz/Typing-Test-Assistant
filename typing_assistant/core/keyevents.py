"""Telling our own synthetic keystrokes from the user's hands.

Validated by spike (spec section 8): every event we generate carries SIGNATURE
in ``dwExtraInfo``, and Windows independently sets ``LLKHF_INJECTED`` on
synthetic events. Requiring *both* means another automation tool's output is
never mistaken for ours, and a process that somehow set the tag without
injecting cannot impersonate us either.

Measured, not assumed:

    tagged synthetic   vk=0x87  flags=0x10  injected=True   extra=0x54595041
    real keypress      vk=0x09  flags=0x00  injected=False  extra=0x0

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

#: "TYPA". Stamped into dwExtraInfo on every keystroke we send.
SIGNATURE = 0x54595041

LLKHF_EXTENDED = 0x01
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80


@dataclass(frozen=True)
class KeyEvent:
    """One low-level keyboard event, classified."""

    vk: int
    scan: int
    flags: int
    extra_info: int

    @property
    def injected(self) -> bool:
        """Did Windows mark this as synthetic?"""
        return bool(self.flags & LLKHF_INJECTED)

    @property
    def ours(self) -> bool:
        """Injected *and* carrying our signature -- both are required."""
        return self.injected and self.extra_info == SIGNATURE

    @property
    def human(self) -> bool:
        """Came from real hardware, so the user is typing."""
        return not self.injected

    @property
    def is_up(self) -> bool:
        return bool(self.flags & LLKHF_UP)

    @property
    def is_down(self) -> bool:
        return not self.is_up


def classify(vk: int, scan: int, flags: int, extra_info: int) -> KeyEvent:
    """Build a classified :class:`KeyEvent` from raw hook fields."""
    return KeyEvent(vk=vk, scan=scan, flags=flags, extra_info=extra_info)
