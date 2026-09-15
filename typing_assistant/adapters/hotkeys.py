"""Watching the keyboard so a human keypress can stop us instantly.

Runs a WH_KEYBOARD_LL hook on its own thread with a message pump, which is what
such a hook requires. The callback records and returns immediately: Windows
drops a hook whose callback exceeds roughly 300 ms.

No elevation needed -- confirmed by spike (spec section 8, finding 3).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional

from typing_assistant.core.keyevents import classify

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_ssize_t

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
_HC_ACTION = 0

VK_ESCAPE = 0x1B


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


_HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_u32.SetWindowsHookExW.argtypes = (
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.HINSTANCE,
    wintypes.DWORD,
)
_u32.SetWindowsHookExW.restype = wintypes.HHOOK
_u32.CallNextHookEx.argtypes = (
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_u32.CallNextHookEx.restype = LRESULT
_u32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_u32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_u32.PostThreadMessageW.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_u32.ToUnicode.argtypes = (
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_char_p,
    wintypes.LPWSTR,
    ctypes.c_int,
    wintypes.UINT,
)
_u32.ToUnicode.restype = ctypes.c_int
_u32.GetKeyboardState.argtypes = (ctypes.c_char_p,)
_k32.GetCurrentThreadId.restype = wintypes.DWORD


def _vk_to_char(vk: int, scan: int) -> Optional[str]:
    """Best-effort character for a human keypress, for resync matching."""
    state = ctypes.create_string_buffer(256)
    _u32.GetKeyboardState(state)
    buffer = ctypes.create_unicode_buffer(8)
    count = _u32.ToUnicode(vk, scan, state, buffer, len(buffer), 0)
    if count == 1:
        return buffer[0]
    return None


class KeyboardMonitor:
    """Classifies every keystroke and records what the human typed.

    ``pause_requested`` goes true the moment a real key is pressed -- the single
    mechanism that serves as panic stop, "let me take over", and resync trigger.
    ``abort_requested`` goes true for the dedicated abort key.
    """

    def __init__(
        self,
        on_human: Optional[Callable[[str], None]] = None,
        abort_vk: int = VK_ESCAPE,
    ) -> None:
        self._on_human = on_human
        self._abort_vk = abort_vk
        self._hook = None
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._human_chars: list[str] = []
        self.abort_requested = False
        self.pause_requested = False
        self.events_seen = 0
        self.ours_seen = 0
        # Held so ctypes does not garbage-collect the live callback.
        self._proc = _HOOKPROC(self._callback)

    # --- hook plumbing ---

    def _callback(self, code, wparam, lparam):
        if code == _HC_ACTION:
            data = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            event = classify(data.vkCode, data.scanCode, data.flags, data.dwExtraInfo)
            self.events_seen += 1
            if event.ours:
                self.ours_seen += 1
            elif event.human and event.is_down:
                self.pause_requested = True
                if event.vk == self._abort_vk:
                    self.abort_requested = True
                char = _vk_to_char(event.vk, event.scan)
                if char is not None:
                    with self._lock:
                        self._human_chars.append(char)
                    if self._on_human is not None:
                        self._on_human(char)
        return _u32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self) -> None:
        self._thread_id = _k32.GetCurrentThreadId()
        self._hook = _u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._hook:
            return
        message = wintypes.MSG()
        while _u32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            pass
        _u32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    # --- public ---

    def start(self, timeout: float = 2.0) -> bool:
        """Install the hook. Returns whether it was installed successfully."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._hook is not None

    def stop(self) -> None:
        if self._thread_id:
            _u32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def human_text(self) -> str:
        with self._lock:
            return "".join(self._human_chars)

    def clear(self) -> None:
        with self._lock:
            self._human_chars.clear()
        self.abort_requested = False
        self.pause_requested = False

    def is_set(self) -> bool:
        """Adapts to core.typist's abort protocol."""
        return self.pause_requested

    def __enter__(self) -> "KeyboardMonitor":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
