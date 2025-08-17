import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path
from secrets import token_bytes
from hashlib import pbkdf2_hmac

import desktop

CONFIG_PATH = Path(__file__).with_name('config.json')


def load_config():
    if not CONFIG_PATH.exists():
        cfg = {
            "hotkey": "ctrl+alt+u",
            "password": {
                "salt": token_bytes(16).hex(),
                "hash": pbkdf2_hmac('sha256', b'ChangeMe123', token_bytes(16), 200_000).hex(),
                "iterations": 200_000,
                "algo": "pbkdf2_sha256",
            },
            "schedule": {
                "enabled": False,
                "start": "22:00",
                "end": "07:00"
            }
        }
        # Note: above mistakenly uses a random salt for hash generation differently; fix to consistent salt below
        salt = token_bytes(16)
        cfg["password"]["salt"] = salt.hex()
        cfg["password"]["hash"] = pbkdf2_hmac('sha256', b'ChangeMe123', salt, cfg["password"]["iterations"]).hex()
        save_config(cfg)
        return cfg
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def set_password_interactive():
    cfg = load_config()
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
        pwcfg = cfg.setdefault('password', {})
        salt = token_bytes(16)
        pwcfg['salt'] = salt.hex()
        pwcfg['iterations'] = int(pwcfg.get('iterations', 200_000))
        pwcfg['hash'] = pbkdf2_hmac('sha256', p1.encode('utf-8'), salt, pwcfg['iterations']).hex()
        pwcfg['algo'] = 'pbkdf2_sha256'
        save_config(cfg)
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


class Locker:
    def __init__(self):
        self.state = LockState()

    def lock_now(self):
        if self.state.active:
            return
        # Create/open alternate desktop and spawn lockscreen process bound to it
        hdesk = desktop.create_or_open_desktop(desktop.LOCK_DESKTOP)
        # Keep the handle open in this process lifetime
        # Start child process
        cmd = [sys.executable, str(Path(__file__).with_name('lockscreen.py')), '--desktop-name', desktop.LOCK_DESKTOP]
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.state = LockState(process=proc, active=True)
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
        self.state = LockState()



def scheduler_loop(locker: Locker):
    while True:
        cfg = load_config()
        sched = cfg.get('schedule', {})
        enabled = bool(sched.get('enabled', False))
        if not enabled:
            time.sleep(1)
            continue
        try:
            start_str = sched.get('start', '22:00')
            end_str = sched.get('end', '07:00')
            start = dtime.fromisoformat(start_str)
            end = dtime.fromisoformat(end_str)
        except Exception:
            # Invalid schedule; skip
            time.sleep(5)
            continue
        now = datetime.now()
        should_lock = in_lock_window(now, start, end)
        if should_lock and not locker.state.active:
            locker.lock_now()
        elif not should_lock and locker.state.active:
            locker.unlock_now()
        time.sleep(1)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lock-now', action='store_true', help='Lock immediately and show lock screen')
    ap.add_argument('--set-password', action='store_true', help='Set or change the unlock password')
    args = ap.parse_args()

    if args.set_password:
        set_password_interactive()
        return

    locker = Locker()

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
