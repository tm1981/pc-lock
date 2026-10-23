import json
import threading
from pathlib import Path
import ctypes
from ctypes import wintypes

from config import get_app_dir, atomic_write_bytes

DEFAULT_NOTIFY_MINUTES = [5, 1]
_lock = threading.RLock()


def schedule_path() -> Path:
    return get_app_dir() / 'schedule.dat'

# DPAPI
crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

CryptProtectData = crypt32.CryptProtectData
CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
CryptProtectData.restype = wintypes.BOOL

CryptUnprotectData = crypt32.CryptUnprotectData
CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
CryptUnprotectData.restype = wintypes.BOOL

LocalFree = kernel32.LocalFree
LocalFree.argtypes = [wintypes.HLOCAL]
LocalFree.restype = wintypes.HLOCAL


def _dpapi_protect(data: bytes) -> bytes:
    in_blob = DATA_BLOB(len(data), (ctypes.c_byte * len(data)).from_buffer_copy(data))
    out_blob = DATA_BLOB()
    if not CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError('CryptProtectData failed')
    try:
        out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return out
    finally:
        LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = DATA_BLOB(len(data), (ctypes.c_byte * len(data)).from_buffer_copy(data))
    out_blob = DATA_BLOB()
    if not CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError('CryptUnprotectData failed')
    try:
        out = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return out
    finally:
        LocalFree(out_blob.pbData)


def _defaults() -> dict:
    return {"enabled": False, "start": "22:00", "end": "07:00",
            "notify_minutes": list(DEFAULT_NOTIFY_MINUTES), "snooze_until": None}


def read_schedule() -> dict:
    """Return the schedule. `snooze_until` (ISO datetime or None) skips locking until that moment;
    it is set when someone unlocks during a scheduled window so the schedule stays enabled."""
    path = schedule_path()
    if not path.exists():
        return _defaults()
    try:
        with _lock:
            enc = path.read_bytes()
        obj = json.loads(_dpapi_unprotect(enc).decode('utf-8'))
        out = _defaults()
        out["enabled"] = bool(obj.get('enabled', False))
        out["start"] = str(obj.get('start', '22:00'))
        out["end"] = str(obj.get('end', '07:00'))
        notify = obj.get('notify_minutes', DEFAULT_NOTIFY_MINUTES)
        if isinstance(notify, list) and all(isinstance(n, int) and n > 0 for n in notify):
            out["notify_minutes"] = notify
        snooze = obj.get('snooze_until')
        out["snooze_until"] = str(snooze) if snooze else None
        return out
    except Exception:
        # Corrupt store -> disable schedule
        return _defaults()


def write_schedule(enabled: bool, start: str, end: str, notify_minutes: list[int] | None = None,
                   snooze_until: str | None = None) -> None:
    if notify_minutes is None:
        notify_minutes = list(DEFAULT_NOTIFY_MINUTES)
    obj = {"enabled": bool(enabled), "start": str(start), "end": str(end),
           "notify_minutes": notify_minutes, "snooze_until": snooze_until}
    raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    with _lock:
        atomic_write_bytes(schedule_path(), _dpapi_protect(raw))


def update_schedule(**changes) -> dict:
    """Read-modify-write: change only the given fields, keep the rest."""
    with _lock:
        sched = read_schedule()
        sched.update(changes)
        write_schedule(sched['enabled'], sched['start'], sched['end'],
                       sched['notify_minutes'], sched['snooze_until'])
        return sched
