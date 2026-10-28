"""Windows per-session marker for the TranscriptForge desktop application."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

_APP_RUNNING_EVENT = r"Local\TranscriptForge.AppRunning"
_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_NOT_FOUND = 2
_SYNCHRONIZE = 0x00100000


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = (
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class AppInstanceGuard:
    """Keep a named event open for the lifetime of the desktop app."""

    def __init__(self, kernel32=None, handle=None):
        self._kernel32 = kernel32
        self._handle = handle

    @classmethod
    def try_acquire(cls) -> AppInstanceGuard | None:
        if os.name != "nt":
            return cls()

        kernel32 = _kernel32()
        ctypes.set_last_error(0)
        handle = kernel32.CreateEventW(None, True, True, _APP_RUNNING_EVENT)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == _ERROR_ALREADY_EXISTS:
            if not kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            return None
        return cls(kernel32, handle)

    def close(self) -> None:
        if self._handle is None:
            return
        if not self._kernel32.CloseHandle(self._handle):
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = None


def is_desktop_app_running() -> bool:
    """Return whether the desktop app has its per-session event open."""
    if os.name != "nt":
        return False

    kernel32 = _kernel32()
    ctypes.set_last_error(0)
    handle = kernel32.OpenEventW(_SYNCHRONIZE, False, _APP_RUNNING_EVENT)
    if handle:
        if not kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        return True

    error = ctypes.get_last_error()
    if error == _ERROR_FILE_NOT_FOUND:
        return False
    raise ctypes.WinError(error)
