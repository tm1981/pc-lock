import os
import json
from pathlib import Path
import ctypes
from ctypes import wintypes

from config import get_app_dir
SCHEDULE_PATH = get_app_dir() / 'schedule.dat'

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


def read_schedule() -> dict:
    if not SCHEDULE_PATH.exists():
        # Return defaults
        return {"enabled": False, "start": "22:00", "end": "07:00", "notify_minutes": [5, 1]}
    try:
        enc = SCHEDULE_PATH.read_bytes()
        dec = _dpapi_unprotect(enc)
        obj = json.loads(dec.decode('utf-8'))
        # basic validation
        enabled = bool(obj.get('enabled', False))
        start = str(obj.get('start', '22:00'))
        end = str(obj.get('end', '07:00'))
        notify_minutes = obj.get('notify_minutes', [5, 1])
        if not isinstance(notify_minutes, list):
            notify_minutes = [5, 1]
        return {"enabled": enabled, "start": start, "end": end, "notify_minutes": notify_minutes}
    except Exception:
        # Corrupt store -> disable schedule
        return {"enabled": False, "start": "22:00", "end": "07:00", "notify_minutes": [5, 1]}


def write_schedule(enabled: bool, start: str, end: str, notify_minutes: list[int] | None = None) -> None:
    if notify_minutes is None:
        notify_minutes = [5, 1]
    obj = {"enabled": bool(enabled), "start": str(start), "end": str(end), "notify_minutes": notify_minutes}
    raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    enc = _dpapi_protect(raw)
    SCHEDULE_PATH.write_bytes(enc)
