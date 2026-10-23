"""
Named event used by a second launch to ask the running instance to show its window.
"""
import ctypes
from ctypes import wintypes

_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD

EVENT_NAME = 'Local\\PC_LOCK_SHOW_WINDOW'
WAIT_OBJECT_0 = 0

_handle = None


def _event():
    global _handle
    if _handle is None:
        # auto-reset event: each SetEvent wakes exactly one poll
        _handle = _k32.CreateEventW(None, False, False, EVENT_NAME)
    return _handle


def signal_show() -> None:
    h = _event()
    if h:
        _k32.SetEvent(h)


def show_requested() -> bool:
    """Non-blocking check; call periodically from the UI thread."""
    h = _event()
    return bool(h) and _k32.WaitForSingleObject(h, 0) == WAIT_OBJECT_0
