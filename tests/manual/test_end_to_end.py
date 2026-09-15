"""End-to-end verification: the real keyboard adapter into a real window.

    pytest tests/manual/test_end_to_end.py -v -m manual -s

Deviates from the plan deliberately. The plan said to type into the practice
page in a browser, with "the browser window must stay focused". That is unsafe:
SendInput goes to whatever has OS focus, so a mistargeted run types a whole
passage into whatever the user happens to have open. Instead these tests create
their own always-on-top Tk window, and prove keystrokes are landing in it by
sending a single sentinel character first. If the sentinel does not arrive the
test skips rather than typing anything further.

The browser practice target remains the right tool for eyeballing rhythm and
recolour behaviour by hand; it is not needed to measure WPM.
"""

from __future__ import annotations

import ctypes
import random
import threading
import tkinter as tk

import pytest

from typing_assistant.adapters.clock import SystemClock
from typing_assistant.adapters.hotkeys import KeyboardMonitor
from typing_assistant.adapters.keyboard import SendInputKeyboard
from typing_assistant.core.pacing import PacingConfig, schedule
from typing_assistant.core.typist import type_schedule

pytestmark = pytest.mark.manual

PASSAGE = "The quick brown fox jumps over the lazy dog."
PUNCTUATION = "Mr. Smith paid 3.14 dollars, e.g. a small sum. Dr. Jones agreed."


_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_GA_ROOT = 2
_SW_SHOW = 5


def _force_foreground(child_hwnd: int) -> int:
    """Take real Windows foreground focus, not just Tk-internal focus.

    Tk's focus_force only moves focus within Tk. SendInput goes to whatever has
    OS foreground, so without this the keystrokes land in the console that
    launched pytest. Windows restricts SetForegroundWindow from a process that
    does not already own the foreground, so we attach to the current foreground
    thread's input queue first.
    """
    hwnd = _u32.GetAncestor(child_hwnd, _GA_ROOT) or child_hwnd
    foreground = _u32.GetForegroundWindow()
    target_thread = _u32.GetWindowThreadProcessId(foreground, None)
    own_thread = _k32.GetCurrentThreadId()

    _u32.AttachThreadInput(own_thread, target_thread, True)
    try:
        _u32.ShowWindow(hwnd, _SW_SHOW)
        _u32.BringWindowToTop(hwnd)
        _u32.SetForegroundWindow(hwnd)
        _u32.SetActiveWindow(hwnd)
        _u32.SetFocus(hwnd)
    finally:
        _u32.AttachThreadInput(own_thread, target_thread, False)
    return hwnd


class _Target:
    """An always-on-top entry box that receives the keystrokes."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("typing-assistant e2e target")
        self.root.geometry("600x90+80+80")
        self.root.attributes("-topmost", True)
        self.entry = tk.Entry(self.root, width=80)
        self.entry.pack(padx=10, pady=20, fill="x")
        self.entry.focus_set()
        self.root.lift()
        self.pump()
        self.hwnd = _force_foreground(self.root.winfo_id())
        self.pump()

    @property
    def has_foreground(self) -> bool:
        return _u32.GetForegroundWindow() == self.hwnd

    def pump(self, cycles: int = 30) -> None:
        for _ in range(cycles):
            self.root.update()

    @property
    def text(self) -> str:
        return self.entry.get()

    def clear(self) -> None:
        self.entry.delete(0, tk.END)
        self.pump()

    def close(self) -> None:
        self.root.destroy()


def _type_into(box: "_Target", keystrokes):
    """Type while the target pumps its message loop, as a real app would.

    Two things this handles, both learned the hard way.

    *Pumping.* A real target application processes messages continuously. An
    earlier version let every key message queue up and pumped only at the end,
    which is not how any real window behaves.

    *Interference.* These tests steal foreground focus and type into a window.
    If the machine's owner is using it -- clicks elsewhere, touches the keyboard
    -- their keystrokes land in the entry box and the assertion fails for a
    reason that has nothing to do with the code. That produced a confusing
    intermittent "extra space" until the real cause turned out to be a stray
    keypress. So the run is watched by the same KeyboardMonitor the product
    uses: any genuine human keystroke aborts it, and the test skips rather than
    reporting a false failure. This also means the monitor's abort path gets
    exercised for real, which no unit test can do.
    """
    keyboard = SendInputKeyboard()
    monitor = KeyboardMonitor()
    if not monitor.start():
        pytest.skip("could not install the keyboard hook")

    result = {}

    def run():
        with SystemClock() as clock:
            result["value"] = type_schedule(keystrokes, keyboard, clock, abort=monitor)

    try:
        monitor.clear()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        while worker.is_alive():
            box.root.update()
        worker.join(timeout=5.0)
        box.pump(60)
        outcome = result["value"]

        if outcome.aborted:
            pytest.skip(
                "real keyboard input arrived during the run "
                f"({monitor.human_text!r}); results would be contaminated. "
                "Re-run without touching the keyboard."
            )
        if not box.has_foreground:
            pytest.skip("lost foreground focus mid-run; results would be unreliable")
    finally:
        monitor.stop()

    return outcome, keyboard


@pytest.fixture
def target():
    box = _Target()
    keyboard = SendInputKeyboard()

    # Sentinel: prove keystrokes reach OUR window before sending anything real.
    keyboard.send_char("x")
    box.pump()
    arrived = box.text
    foreground = box.has_foreground
    if arrived != "x":
        box.close()
        pytest.skip(
            f"sentinel keystroke did not reach the test window (got {arrived!r}, "
            f"foreground={foreground}); refusing to type into an unknown target"
        )
    box.clear()
    try:
        yield box
    finally:
        box.close()


@pytest.mark.parametrize("target_wpm", [40.0, 55.0, 70.0])
def test_measured_wpm_lands_within_tolerance(target, target_wpm):
    """Acceptance criterion from spec 9.6: measured WPM within 2 of target."""
    keystrokes = schedule(PASSAGE, PacingConfig(wpm=target_wpm), random.Random(1))
    result, keyboard = _type_into(target, keystrokes)

    print(f"\n  target {target_wpm:g} -> measured {result.wpm:.2f} WPM")
    assert result.sent == PASSAGE
    assert keyboard.unicode_fallbacks == 0
    assert abs(result.wpm - target_wpm) <= 2.0


def test_the_window_receives_exactly_what_was_sent(target):
    """Characters must arrive intact, not mangled by the layout resolution."""
    keystrokes = schedule(PASSAGE, PacingConfig(wpm=120.0), random.Random(2))
    _type_into(target, keystrokes)

    assert target.text == PASSAGE


def test_punctuation_traps_are_reproduced_faithfully(target):
    """The bug at main.py:190 double-spaced every period. Faithful is default."""
    keystrokes = schedule(PUNCTUATION, PacingConfig(wpm=120.0), random.Random(3))
    _type_into(target, keystrokes)

    assert target.text == PUNCTUATION
    assert "Mr.  Smith" not in target.text
    assert "3. 14" not in target.text
    assert "e.g.  a" not in target.text


def test_mixed_case_and_symbols_survive_shift_handling(target):
    sample = "Hello, World! (42%) #tag @name ~end"
    keystrokes = schedule(sample, PacingConfig(wpm=120.0), random.Random(4))
    _, keyboard = _type_into(target, keystrokes)

    assert target.text == sample
    assert keyboard.unicode_fallbacks == 0
