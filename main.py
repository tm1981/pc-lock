import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from secrets import token_bytes
from hashlib import pbkdf2_hmac

import desktop
import sys as _sys

CONFIG_PATH = Path(__file__).with_name('config.json')


def load_config():
    from config import load_config as _load
    return _load()


def save_config(cfg):
    from config import save_config as _save
    return _save(cfg)


def install_startup():
    """Add app to HKCU Run so it starts at user logon."""
    try:
        import winreg
        run_key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_SET_VALUE) as key:
            exe = sys.executable
            script = str(Path(__file__).resolve())
            cmd = f'"{exe}" "{script}"'
            winreg.SetValueEx(key, 'PC-Lock', 0, winreg.REG_SZ, cmd)
        print('Installed startup entry in HKCU Run.')
    except Exception as e:
        print(f'Failed to install startup entry: {e}')


def uninstall_startup():
    """Remove app from HKCU Run."""
    try:
        import winreg
        run_key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, 'PC-Lock')
                print('Removed startup entry from HKCU Run.')
            except FileNotFoundError:
                print('Startup entry not present.')
    except Exception as e:
        print(f'Failed to remove startup entry: {e}')


def set_password_interactive():
    print('Set a new unlock password:')
    while True:
        import getpass
        p1 = getpass.getpass('New password: ')
        p2 = getpass.getpass('Confirm password: ')
        if p1 != p2:
            print('Passwords do not match. Try again.')
            continue
        if len(p1) < 4:
            print('Password too short (min 4 chars).')
            continue
        from config import set_password as _set
        _set(p1)
        print('Password updated.')
        return

def in_lock_window(now: datetime, start: dtime, end: dtime) -> bool:
    cur = now.time()
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    # overnight
    return cur >= start or cur < end


@dataclass
class LockState:
    process: subprocess.Popen | None = None
    active: bool = False
    reason: str | None = None
    start: str | None = None
    end: str | None = None


class Locker:
    def __init__(self):
        self.state = LockState()
        self._watch_thread = None
        self.override_until: datetime | None = None
        self._prev_muted: int | None = None

    def _watch_child(self, proc: subprocess.Popen):
        try:
            proc.wait()
        except Exception:
            pass
        # If the same process is still referenced, mark as inactive
        if self.state.process is proc:
            # If current lock was schedule-initiated, disable schedule on manual unlock
            try:
                if self.state.reason == 'schedule':
                    from schedule_store import read_schedule, write_schedule
                    sched = read_schedule()
                    if bool(sched.get('enabled', False)):
                        write_schedule(False, sched.get('start', '22:00'), sched.get('end', '07:00'))
            except Exception:
                pass
            # Clear state
            self.state = LockState()

    def _mute_system(self):
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            current = int(volume.GetMute())
            if self._prev_muted is None:
                self._prev_muted = current
            if current == 0:
                volume.SetMute(1, None)
        except Exception:
            pass

    def _restore_audio(self):
        try:
            if self._prev_muted is None:
                return
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMute(int(self._prev_muted), None)
        except Exception:
            pass
        finally:
            self._prev_muted = None

    def lock_now(self, reason: str = 'manual', start: str | None = None, end: str | None = None):
        if self.state.active:
            return
        # Mute audio (A1)
        self._mute_system()
        # Create/open alternate desktop and spawn lockscreen process bound to it
        hdesk = desktop.create_or_open_desktop(desktop.LOCK_DESKTOP)
        # Keep the handle open in this process lifetime
        # Start child process
        if getattr(_sys, 'frozen', False):
            # Relaunch the same EXE in lockscreen mode
            cmd = [sys.executable, '--mode', 'lockscreen', '--desktop-name', desktop.LOCK_DESKTOP, '--reason', reason]
            if reason == 'schedule' and start and end:
                cmd += ['--start', start, '--end', end]
        else:
            cmd = [sys.executable, str(Path(__file__).with_name('lockscreen.py')), '--desktop-name', desktop.LOCK_DESKTOP, '--reason', reason]
            if reason == 'schedule' and start and end:
                cmd += ['--start', start, '--end', end]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        # Hide any console window for child on Windows
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            flags |= subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, creationflags=flags)
        self.state = LockState(process=proc, active=True, reason=reason, start=start, end=end)
        # Start watcher to reset state when child exits (e.g., after password unlock)
        try:
            import threading
            self._watch_thread = threading.Thread(target=self._watch_child, args=(proc,), daemon=True)
            self._watch_thread.start()
        except Exception:
            pass
        # Do not close hdesk yet; keeping handle open ensures desktop persists
        # We intentionally leak hdesk here; the OS will clean up on exit.

    def unlock_now(self):
        if not self.state.active:
            return
        # Switch back to default desktop (best-effort)
        try:
            hdef = desktop.open_desktop(desktop.DEFAULT_DESKTOP)
            desktop.switch_desktop(hdef)
            desktop.close_desktop(hdef)
        except Exception:
            pass
        # Terminate child process if still alive
        if self.state.process and self.state.process.poll() is None:
            try:
                self.state.process.send_signal(signal.CTRL_BREAK_EVENT)
                # Give it a moment to exit
                for _ in range(20):
                    if self.state.process.poll() is not None:
                        break
                    time.sleep(0.1)
            except Exception:
                pass
            try:
                self.state.process.terminate()
            except Exception:
                pass
        # Restore audio
        self._restore_audio()
        self.state = LockState()



def scheduler_loop(locker: Locker):
    while True:
        from schedule_store import read_schedule
        sched = read_schedule()
        if not bool(sched.get('enabled', False)):
            time.sleep(1)
            continue
        try:
            start = dtime.fromisoformat(sched.get('start', '22:00'))
            end = dtime.fromisoformat(sched.get('end', '07:00'))
        except Exception:
            time.sleep(5)
            continue
        now = datetime.now()
        should_lock = in_lock_window(now, start, end)
        if should_lock and not locker.state.active:
            locker.lock_now(reason='schedule', start=start.isoformat(timespec='minutes'), end=end.isoformat(timespec='minutes'))
        elif not should_lock and locker.state.active:
            locker.unlock_now()
        time.sleep(1)


def lock_if_in_schedule_now(locker: Locker):
    from schedule_store import read_schedule
    sched = read_schedule()
    if not bool(sched.get('enabled', False)):
        return
    try:
        start = dtime.fromisoformat(sched.get('start', '22:00'))
        end = dtime.fromisoformat(sched.get('end', '07:00'))
    except Exception:
        return
    if in_lock_window(datetime.now(), start, end):
        locker.lock_now(reason='schedule', start=start.isoformat(timespec='minutes'), end=end.isoformat(timespec='minutes'))



def _ensure_single_instance():
    """Ensure only one scheduler/GUI instance runs. Lock screen child is exempt.
    Uses a named global mutex via Win32 API to avoid pywin32 dependency issues in packaged exe.
    """
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE
        GetLastError = kernel32.GetLastError
        ERROR_ALREADY_EXISTS = 183
        # Create a global mutex
        name = 'Global\\PC_LOCK_SINGLETON'
        hmutex = CreateMutexW(None, True, name)
        if not hmutex:
            return None
        if GetLastError() == ERROR_ALREADY_EXISTS:
            # Another instance is running – try to bring it to front
            try:
                FindWindowW = user32.FindWindowW
                ShowWindow = user32.ShowWindow
                SetForegroundWindow = user32.SetForegroundWindow
                SW_SHOW = 5
                hwnd = FindWindowW(None, 'PC Lock')
                if hwnd:
                    ShowWindow(hwnd, SW_SHOW)
                    SetForegroundWindow(hwnd)
            except Exception:
                pass
            sys.exit(0)
        # Keep handle referenced so mutex stays held
        return hmutex
    except Exception:
        return None


def main():
    from api import maybe_start_api

    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['scheduler', 'lockscreen'], default='scheduler', help='Internal modes for packaged exe')
    ap.add_argument('--ui', action='store_true', help='Launch GUI manager instead of console scheduler')
    ap.add_argument('--lock-now', action='store_true', help='Lock immediately and show lock screen')
    ap.add_argument('--set-password', action='store_true', help='Set or change the unlock password')
    ap.add_argument('--install-startup', action='store_true', help='Install auto-start entry (current user)')
    ap.add_argument('--uninstall-startup', action='store_true', help='Remove auto-start entry (current user)')
    # passthrough for lockscreen mode
    ap.add_argument('--desktop-name', default=desktop.LOCK_DESKTOP)
    ap.add_argument('--reason', choices=['manual', 'schedule'], default='manual')
    ap.add_argument('--start')
    ap.add_argument('--end')
    args = ap.parse_args()

    if args.set_password:
        set_password_interactive()
        return

    if args.install_startup:
        install_startup()
        return

    if args.uninstall_startup:
        uninstall_startup()
        return

    # If packaged exe is invoked in lockscreen mode, run lockscreen now
    if args.mode == 'lockscreen':
        import lockscreen as _lock
        # Reuse parsed args for consistency
        sys.argv = [sys.argv[0], '--desktop-name', args.desktop_name, '--reason', args.reason] + ([] if not args.start or not args.end else ['--start', args.start, '--end', args.end])
        _lock.main()
        return

    # Single-instance guard (scheduler/GUI only)
    _ensure_single_instance()

    # If running as packaged exe, default to GUI manager
    if getattr(_sys, 'frozen', False) and args.mode == 'scheduler' and not args.lock_now:
        import ui as _ui
        _ui.root = _ui.tk.Tk()
        _ui.app = _ui.AppUI(_ui.root)
        _ui.root.mainloop()
        return

    # UI mode if requested (dev mode)
    if args.ui:
        import ui as _ui
        _ui.root = _ui.tk.Tk()  # ensure root defined
        _ui.app = _ui.AppUI(_ui.root)
        _ui.root.mainloop()
        return

    locker = Locker()

    # Start REST API if enabled in config
    api_server = maybe_start_api(locker)

    # Lock immediately if we're currently inside the scheduled window
    lock_if_in_schedule_now(locker)

    if args.lock_now:
        locker.lock_now()
        # Keep parent alive to allow CTRL+C and for schedule to potentially unlock
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            locker.unlock_now()
            return

    print('PC Lock scheduler running. Press Ctrl+C to exit.')
    try:
        scheduler_loop(locker)
    except KeyboardInterrupt:
        locker.unlock_now()
        print('Exiting.')


if __name__ == '__main__':
    main()
