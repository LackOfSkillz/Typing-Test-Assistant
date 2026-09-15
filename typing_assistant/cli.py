"""Command line entry point.

    python -m typing_assistant type --text "hello" --wpm 55
    python -m typing_assistant type --file passage.txt --wpm 45
    python -m typing_assistant calibrate --wpm 55

Arming never starts a countdown. It waits indefinitely for the go key, so there
is no timed interaction to race -- the fixed eight-second sleep at
``main.py:95`` is gone.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import sys
import time
from typing import Optional, Sequence

from typing_assistant.adapters import store
from typing_assistant.adapters.clock import SystemClock
from typing_assistant.adapters.hotkeys import KeyboardMonitor
from typing_assistant.adapters.keyboard import SendInputKeyboard
from typing_assistant.core.calibration import calibration_factor, within_tolerance
from typing_assistant.core.pacing import PacingConfig, SpacingMode, schedule
from typing_assistant.core.text import normalize
from typing_assistant.core.typist import type_schedule

CALIBRATION_PASSAGE = (
    "The quick brown fox jumps over the lazy dog. Pack my box with five dozen "
    "liquor jugs. How vexingly quick daft zebras jump. Bright vixens jump for "
    "the lazy dogs and the quick brown foxes watch them go."
)


def _read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        return pathlib.Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _wait_for_go(settle: float = 0.4) -> None:
    """Block until the user presses Enter in this console."""
    print("Click into your target window, then press Enter here to start.")
    print("While typing: any key pauses, Escape aborts.")
    sys.stdin.readline()
    # A moment for focus to settle back on the target window.
    time.sleep(settle)


def _run_typing(
    text: str, wpm: float, spacing: SpacingMode, seed: Optional[int]
) -> int:
    prepared = normalize(text)
    if not prepared:
        print("Nothing to type.", file=sys.stderr)
        return 2

    factor = store.load_calibration()
    config = PacingConfig(wpm=wpm, calibration=factor, spacing=spacing)
    rng = random.Random(seed)
    keystrokes = schedule(prepared, config, rng)

    print(f"{len(prepared)} characters at {wpm:g} WPM (calibration {factor:.3f}).")
    _wait_for_go()

    keyboard = SendInputKeyboard()
    monitor = KeyboardMonitor()
    if not monitor.start():
        print(
            "Could not install the keyboard hook; abort would not work.",
            file=sys.stderr,
        )
        return 3

    try:
        with SystemClock() as clock:
            if not clock.high_resolution:
                print("Warning: high-resolution timer unavailable; rhythm may be coarse.")
            monitor.clear()
            result = type_schedule(keystrokes, keyboard, clock, abort=monitor)
    finally:
        monitor.stop()

    print()
    print(f"Sent {len(result.sent)} of {len(prepared)} characters.")
    print(f"Measured {result.wpm:.1f} WPM in {result.elapsed:.2f}s.")
    if keyboard.unicode_fallbacks:
        print(f"{keyboard.unicode_fallbacks} character(s) needed the Unicode fallback.")
    if result.aborted:
        reason = "Escape" if monitor.abort_requested else "a keypress"
        print(f"Stopped early by {reason}.")
        typed_by_hand = monitor.human_text
        if typed_by_hand:
            print(f"You typed {len(typed_by_hand)} character(s) while it was stopped.")
        return 1
    return 0


def _run_calibration(wpm: float, rounds: int) -> int:
    print("Calibration types a known passage into this console.")
    print("Focus this window and do not touch the keyboard while it runs.\n")
    factor = store.load_calibration()
    keyboard = SendInputKeyboard()

    for round_number in range(1, rounds + 1):
        config = PacingConfig(wpm=wpm, calibration=factor)
        keystrokes = schedule(CALIBRATION_PASSAGE, config, random.Random(round_number))
        _wait_for_go()
        with SystemClock() as clock:
            result = type_schedule(keystrokes, keyboard, clock)
        print()
        print(f"Round {round_number}: asked {wpm:g}, measured {result.wpm:.1f} WPM.")
        if result.aborted:
            print("Aborted; calibration unchanged.")
            return 1
        if within_tolerance(wpm, result.wpm):
            print(f"Within tolerance. Factor {factor:.3f}.")
            break
        factor = calibration_factor(wpm, result.wpm, previous=factor)
        print(f"Adjusted factor to {factor:.3f}.")

    path = store.save_calibration(factor)
    print(f"Saved to {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typing_assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    type_parser = subparsers.add_parser("type", help="type a block of text")
    source = type_parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="text to type")
    source.add_argument("--file", help="file whose contents to type")
    type_parser.add_argument("--wpm", type=float, default=55.0)
    type_parser.add_argument(
        "--double-space",
        action="store_true",
        help="double-space after sentence-ending periods (default: reproduce the source)",
    )
    type_parser.add_argument("--seed", type=int, default=None)

    cal_parser = subparsers.add_parser("calibrate", help="measure this machine")
    cal_parser.add_argument("--wpm", type=float, default=55.0)
    cal_parser.add_argument("--rounds", type=int, default=3)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "type":
        spacing = SpacingMode.DOUBLE if args.double_space else SpacingMode.FAITHFUL
        return _run_typing(_read_text(args), args.wpm, spacing, args.seed)
    return _run_calibration(args.wpm, args.rounds)
