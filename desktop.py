import ctypes
from ctypes import wintypes

# Win32 constants
U32 = ctypes.WinDLL('user32', use_last_error=True)
K32 = ctypes.WinDLL('kernel32', use_last_error=True)

# Desktop access rights
DESKTOP_READOBJECTS      = 0x0001
DESKTOP_CREATEWINDOW     = 0x0002
DESKTOP_ENUMERATE        = 0x0040
DESKTOP_WRITEOBJECTS     = 0x0080
DESKTOP_SWITCHDESKTOP    = 0x0100
GENERIC_ALL              = 0x10000000

# Structures
LPSECURITY_ATTRIBUTES = wintypes.LPVOID  # None for default

# Function prototypes
U32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR,  # lpszDesktop
    wintypes.LPCWSTR,  # lpszDevice (must be None)
    wintypes.LPVOID,   # pDevmode (must be None)
    wintypes.DWORD,    # dwFlags (0)
    wintypes.DWORD,    # dwDesiredAccess
    LPSECURITY_ATTRIBUTES  # lpsa
]
U32.CreateDesktopW.restype = wintypes.HANDLE

U32.OpenDesktopW.argtypes = [
    wintypes.LPCWSTR,  # lpszDesktop
    wintypes.DWORD,    # dwFlags
    wintypes.BOOL,     # fInherit
    wintypes.DWORD     # dwDesiredAccess
]
U32.OpenDesktopW.restype = wintypes.HANDLE

U32.SwitchDesktop.argtypes = [wintypes.HANDLE]
U32.SwitchDesktop.restype = wintypes.BOOL

U32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
U32.SetThreadDesktop.restype = wintypes.BOOL

U32.CloseDesktop.argtypes = [wintypes.HANDLE]
U32.CloseDesktop.restype = wintypes.BOOL

U32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
U32.OpenInputDesktop.restype = wintypes.HANDLE

U32.GetThreadDesktop.argtypes = [wintypes.DWORD]
U32.GetThreadDesktop.restype = wintypes.HANDLE

K32.GetLastError.argtypes = []
K32.GetLastError.restype = wintypes.DWORD

DEFAULT_DESKTOP = 'Default'
LOCK_DESKTOP = 'LockDesktop'

ACCESS = (
    DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
    | DESKTOP_SWITCHDESKTOP
)


def _raise_last_error(prefix: str):
    err = K32.GetLastError()
    raise OSError(f"{prefix} failed with error {err}")


def create_or_open_desktop(name: str = LOCK_DESKTOP):
    """Create a desktop if not exists, else open it. Returns HDESK handle.
    Note: caller must CloseDesktop(handle) when done.
    """
    hdesk = U32.CreateDesktopW(name, None, None, 0, ACCESS, None)
    if not hdesk:
        # Try open existing
        hdesk = U32.OpenDesktopW(name, 0, False, ACCESS)
        if not hdesk:
            _raise_last_error('Create/OpenDesktop')
    return hdesk


def open_desktop(name: str):
    hdesk = U32.OpenDesktopW(name, 0, False, ACCESS)
    if not hdesk:
        _raise_last_error('OpenDesktop')
    return hdesk


def open_input_desktop():
    hdesk = U32.OpenInputDesktop(0, False, ACCESS)
    if not hdesk:
        _raise_last_error('OpenInputDesktop')
    return hdesk


def switch_desktop(hdesk) -> None:
    if not U32.SwitchDesktop(hdesk):
        _raise_last_error('SwitchDesktop')


def set_thread_desktop(hdesk) -> None:
    if not U32.SetThreadDesktop(hdesk):
        _raise_last_error('SetThreadDesktop')


def close_desktop(hdesk) -> None:
    if hdesk and not U32.CloseDesktop(hdesk):
        _raise_last_error('CloseDesktop')
