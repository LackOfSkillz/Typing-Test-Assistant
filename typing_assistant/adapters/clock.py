"""High-resolution sleeping.

Windows' timer resolution can be as coarse as 15.625 ms. At 55 WPM a character
interval is ~218 ms, so that quantisation would be 7% jitter -- enough to distort
the rhythm core.pacing shaped deliberately.

Measured caveat: 15.625 ms is the *coarsest* value, not necessarily the current
one. On the development machine NtQueryTimerResolution reported current=1.000 ms
because an unrelated process had already raised it, and time.sleep was equally
accurate there. The point of this timer is not that it is faster, but that it is
fine-grained whether or not anything else on the machine has raised the global
resolution -- so pacing does not silently degrade depending on what the user
happens to be running. It also avoids timeBeginPeriod, which would raise that
resolution globally on the user's behalf.

Requires Windows 10 1803 or newer for CREATE_WAITABLE_TIMER_HIGH_RESOLUTION;
falls back to time.sleep otherwise, and reports which it got.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_CREATE_WAITABLE_TIMER_MANUAL_RESET = 0x00000001
_CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
_TIMER_ALL_ACCESS = 0x1F0003
_INFINITE = 0xFFFFFFFF

_k32.CreateWaitableTimerExW.argtypes = (
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
)
_k32.CreateWaitableTimerExW.restype = wintypes.HANDLE
_k32.SetWaitableTimer.argtypes = (
    wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_longlong),
    ctypes.c_long,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.BOOL,
)
_k32.SetWaitableTimer.restype = wintypes.BOOL
_k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)


class SystemClock:
    """Real time source. ``high_resolution`` says whether the timer was available."""

    def __init__(self) -> None:
        self._handle = _k32.CreateWaitableTimerExW(
            None,
            None,
            _CREATE_WAITABLE_TIMER_MANUAL_RESET
            | _CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
            _TIMER_ALL_ACCESS,
        )
        self.high_resolution = bool(self._handle)

    def now(self) -> float:
        return time.perf_counter()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if not self._handle:
            time.sleep(seconds)
            return
        # Negative means a relative interval, in units of 100 nanoseconds.
        due = ctypes.c_longlong(-int(seconds * 10_000_000))
        if not _k32.SetWaitableTimer(
            self._handle, ctypes.byref(due), 0, None, None, False
        ):
            time.sleep(seconds)
            return
        _k32.WaitForSingleObject(self._handle, _INFINITE)

    def close(self) -> None:
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None
            self.high_resolution = False

    def __enter__(self) -> "SystemClock":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
