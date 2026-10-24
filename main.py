import argparse
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import desktop
from scheduler import SchedulerThread, in_lock_window, snooze_current_window  # noqa: F401 (re-export)

STARTUP_VALUE_NAME = 'PC-Lock'
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command() -> str:
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    # Prefer pythonw so no console window appears at logon
    exe = Path(sys.executable)
    pythonw = exe.with_name('pythonw.exe')
    exe = pythonw if pythonw.exists() else exe
    return f'"{exe}" "{Path(__file__).resolve()}" --ui'


def is_startup_installed() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return True
    except OSError:
        return False


def install_startup():
    """Add app to HKCU Run so it starts at user logon."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())


def uninstall_startup():
    """Remove app from HKCU Run."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, STARTUP_VALUE_NAME)
        except FileNotFoundError:
            pass


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


def _endpoint_volume():
    """Speaker IAudioEndpointVolume; supports both old and new pycaw APIs."""
    from pycaw.pycaw import AudioUtilities
    speakers = AudioUtilities.GetSpeakers()
    if hasattr(speakers, 'EndpointVolume'):  # pycaw >= 2025
        return speakers.EndpointVolume
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _with_com(fn):
    """Run fn with COM initialised: lock/unlock is called from scheduler, API and UI threads."""
    import comtypes
    comtypes.CoInitialize()
    try:
        return fn()
    finally:
        comtypes.CoUninitialize()


def _switch_to_default_desktop():
    try:
        hdef = desktop.open_desktop(desktop.DEFAULT_DESKTOP)
        try:
            desktop.switch_desktop(hdef)
        finally:
            desktop.close_desktop(hdef)
    except Exception as e:
        print(f'[locker] switch to default desktop failed: {e}')


@dataclass
class LockState:
    process: subprocess.Popen | None = None
    active: bool = False
    reason: str | None = None
    start: str | None = None
    end: str | None = None
    since: datetime | None = None


class Locker:
    MAX_RESPAWN_DELAY = 30.0  # seconds; lock screen restarts back off up to this

    def __init__(self):
        self.state = LockState()
        self._mutex = threading.RLock()
        self._hdesk = None  # kept open for the app lifetime so the lock desktop persists
        self._prev_muted: int | None = None

    # --- audio -----------------------------------------------------------------
    def _mute_system(self):
        def mute():
            volume = _endpoint_volume()
            if self._prev_muted is None:
                self._prev_muted = int(volume.GetMute())
            volume.SetMute(1, None)
        try:
            _with_com(mute)
        except Exception as e:
            print(f'[locker] mute failed: {e}')

    def _restore_audio(self):
        if self._prev_muted is None:
            return
        prev, self._prev_muted = self._prev_muted, None
        try:
            _with_com(lambda: _endpoint_volume().SetMute(prev, None))
        except Exception as e:
            print(f'[locker] restore audio failed: {e}')

    # --- lock screen process -----------------------------------------------------
    def _spawn(self, reason: str, start: str | None, end: str | None) -> subprocess.Popen:
        if self._hdesk is None:
            self._hdesk = desktop.create_or_open_desktop(desktop.LOCK_DESKTOP)
        if getattr(sys, 'frozen', False):
            # Relaunch the same EXE in lockscreen mode
            cmd = [sys.executable, '--mode', 'lockscreen']
        else:
            cmd = [sys.executable, str(Path(__file__).with_name('lockscreen.py'))]
        cmd += ['--desktop-name', desktop.LOCK_DESKTOP, '--reason', reason]
        if reason == 'schedule' and start and end:
            cmd += ['--start', start, '--end', end]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        return subprocess.Popen(cmd, creationflags=flags)

    def _respawn_delay(self, respawns: int) -> float:
        return 0.0 if respawns == 0 else min(self.MAX_RESPAWN_DELAY, 0.5 * 2 ** respawns)

    def _watch_child(self, proc: subprocess.Popen, respawns: int):
        code = proc.wait()
        # Fail closed: only exit code 0 (correct password on the lock screen) ends the lock.
        # Crash / Alt+F4 / failed spawn: keep restarting the lock screen with backoff, forever.
        while code != 0:
            print(f'[locker] lock screen exited with {code}; restarting')
            time.sleep(self._respawn_delay(respawns))
            respawns += 1
            with self._mutex:
                if self.state.process is not proc:
                    return  # unlocked meanwhile via unlock_now
                try:
                    proc = self._spawn(self.state.reason, self.state.start, self.state.end)
                    self.state.process = proc
                except Exception as e:
                    print(f'[locker] respawn failed: {e}')
                    continue  # still locked; the desktop stays on LockDesktop
            code = proc.wait()
        with self._mutex:
            if self.state.process is not proc:
                return  # we ended this lock ourselves (unlock_now)
            reason = self.state.reason
            self.state = LockState()
        _switch_to_default_desktop()  # never leave the user on an empty lock desktop
        self._restore_audio()
        if reason == 'schedule':
            # Keep the schedule enabled but don't re-lock for the rest of this window
            try:
                snooze_current_window()
            except Exception as e:
                print(f'[locker] snooze failed: {e}')

    def lock_now(self, reason: str = 'manual', start: str | None = None, end: str | None = None):
        with self._mutex:
            if self.state.active:
                return
            self._mute_system()
            try:
                proc = self._spawn(reason, start, end)
            except Exception:
                self._restore_audio()
                raise
            self.state = LockState(process=proc, active=True, reason=reason, start=start, end=end,
                                   since=datetime.now())
            threading.Thread(target=self._watch_child, args=(proc, 0), daemon=True).start()

    def unlock_now(self, snooze: bool = True):
        """End the lock. With snooze=True an unlock inside the scheduled window skips the rest of it,
        otherwise the scheduler would re-lock a second later."""
        with self._mutex:
            if not self.state.active:
                return
            proc, reason = self.state.process, self.state.reason
            # Clear state first so the watcher thread knows this exit was intentional
            self.state = LockState()
        _switch_to_default_desktop()
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
        self._restore_audio()
        if snooze and reason == 'schedule':
            try:
                snooze_current_window()
            except Exception as e:
                print(f'[locker] snooze failed: {e}')

    def status(self) -> dict:
        s = self.state
        return {
            "locked": bool(s.active),
            "reason": s.reason,
            "since": s.since.isoformat(timespec='seconds') if s.since else None,
        }


def _ensure_single_instance():
    """Ensure only one scheduler/GUI instance runs. Lock screen child is exempt.
    A second launch signals the running one (via a named event) to show its window, then exits.
    """
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        ERROR_ALREADY_EXISTS = 183
        hmutex = kernel32.CreateMutexW(None, True, 'Global\\PC_LOCK_SINGLETON')
        if not hmutex:
            return None
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            from single_instance import signal_show
            signal_show()
            sys.exit(0)
        # Keep handle referenced so mutex stays held
        return hmutex
    except SystemExit:
        raise
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
        print('Installed startup entry in HKCU Run.')
        return

    if args.uninstall_startup:
        uninstall_startup()
        print('Removed startup entry from HKCU Run.')
        return

    # If packaged exe is invoked in lockscreen mode, run lockscreen now
    if args.mode == 'lockscreen':
        import lockscreen as _lock
        sys.argv = [sys.argv[0], '--desktop-name', args.desktop_name, '--reason', args.reason] + ([] if not args.start or not args.end else ['--start', args.start, '--end', args.end])
        _lock.main()
        return

    # Single-instance guard (scheduler/GUI only)
    _ensure_single_instance()

    # GUI: default for the packaged exe, or with --ui
    if args.ui or (getattr(sys, 'frozen', False) and not args.lock_now):
        import ui as _ui
        _ui.main()
        return

    locker = Locker()
    try:
        maybe_start_api(locker)
    except OSError as e:
        print(f'API server not started: {e}')
    scheduler = SchedulerThread(locker)
    scheduler.start()

    if args.lock_now:
        locker.lock_now()

    print('PC Lock scheduler running. Press Ctrl+C to exit.')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        locker.unlock_now(snooze=False)
        print('Exiting.')


if __name__ == '__main__':
    main()
