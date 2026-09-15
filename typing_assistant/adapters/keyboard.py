"""Sending keystrokes through SendInput, stamped so we can recognise our own.

Replaces pyautogui, which cost ~1.8 ms per call of pure overhead (spec section 8)
and resolved characters in a layout-dependent way that broke on non-US layouts.

Character resolution goes through VkKeyScanW to a real virtual key plus shift
state, with the scan code from MapVirtualKeyW. Both wVk and wScan are set and
KEYEVENTF_SCANCODE is *not* used, so consumers reading either the virtual key or
the scan code see correct values. KEYEVENTF_UNICODE is a fallback only: it
arrives as VK_PACKET (0xE7), and anything reading keyCode would see 231.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from typing_assistant.core.keyevents import SIGNATURE

_u32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12

#: VkKeyScanW packs the required modifiers into the high byte.
_SHIFT_REQUIRED = 1
_CTRL_REQUIRED = 2
_ALT_REQUIRED = 4


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_u32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_u32.SendInput.restype = wintypes.UINT
_u32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
_u32.VkKeyScanW.restype = wintypes.SHORT
_u32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_u32.MapVirtualKeyW.restype = wintypes.UINT


def _key_event(vk: int, scan: int, up: bool, unicode_char: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if unicode_char:
        flags |= KEYEVENTF_UNICODE
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.ki = KEYBDINPUT(
        wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=SIGNATURE
    )
    return item


class SendInputKeyboard:
    """Types characters as though they came from the physical keyboard."""

    def __init__(self) -> None:
        self.unicode_fallbacks = 0

    # --- low level ---

    def _send(self, *events: INPUT) -> int:
        array = (INPUT * len(events))(*events)
        return _u32.SendInput(len(events), array, ctypes.sizeof(INPUT))

    def send_vk(self, vk: int, shift: bool = False) -> None:
        """Press and release *vk*, optionally with Shift held."""
        scan = _u32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        shift_scan = _u32.MapVirtualKeyW(VK_SHIFT, MAPVK_VK_TO_VSC)
        events = []
        if shift:
            events.append(_key_event(VK_SHIFT, shift_scan, up=False))
        events.append(_key_event(vk, scan, up=False))
        events.append(_key_event(vk, scan, up=True))
        if shift:
            events.append(_key_event(VK_SHIFT, shift_scan, up=True))
        self._send(*events)

    def _send_unicode(self, ch: str) -> None:
        self.unicode_fallbacks += 1
        code = ord(ch)
        self._send(
            _key_event(0, code, up=False, unicode_char=True),
            _key_event(0, code, up=True, unicode_char=True),
        )

    # --- public ---

    def send_char(self, ch: str) -> None:
        """Send one character, preferring a real virtual key over Unicode."""
        if ch in ("\n", "\r"):
            self.send_vk(VK_RETURN)
            return
        if ch == "\t":
            self.send_vk(VK_TAB)
            return

        scan_result = _u32.VkKeyScanW(ch)
        if scan_result == -1:
            self._send_unicode(ch)
            return

        vk = scan_result & 0xFF
        modifiers = (scan_result >> 8) & 0xFF
        if modifiers & (_CTRL_REQUIRED | _ALT_REQUIRED):
            # AltGr characters and the like: a modifier dance we do not need to
            # reproduce, and Unicode injection is correct for them.
            self._send_unicode(ch)
            return

        self.send_vk(vk, shift=bool(modifiers & _SHIFT_REQUIRED))

    def send_backspace(self) -> None:
        self.send_vk(VK_BACK)
