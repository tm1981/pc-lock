import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import simpledialog, messagebox

from screeninfo import get_monitors

import desktop

CONFIG_PATH = Path(__file__).with_name('config.json')


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "hotkey": "ctrl+alt+u",
            "password": {
                "salt": None,
                "hash": None,
                "iterations": 200_000,
                "algo": "pbkdf2_sha256",
            },
        }
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def verify_password(cfg, password: str) -> bool:
    from hashlib import pbkdf2_hmac
    pwcfg = cfg.get("password", {})
    salt_hex = pwcfg.get("salt")
    hash_hex = pwcfg.get("hash")
    iterations = int(pwcfg.get("iterations", 200_000))
    if not salt_hex or not hash_hex:
        # No password configured yet -> deny
        return False
    salt = bytes.fromhex(salt_hex)
    calc = pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return calc.hex() == hash_hex


class LockScreen:
    def __init__(self, hotkey: str, message: str = 'This desktop is locked.'):
        self.hotkey = hotkey.lower().replace('+', '-')
        self.message = message
        self.root: tk.Tk | None = None
        self.windows: list[tk.Misc] = []  # Tk or Toplevel
        self.password_unlocked = threading.Event()

    def _build_window_for_monitor(self, m, is_primary: bool = False):
        if is_primary:
            w = tk.Tk()
            self.root = w
        else:
            # Create additional full-screen windows tied to the primary root
            w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        w.configure(bg='black')

        container = tk.Frame(w, bg='black')
        container.place(relx=0.5, rely=0.5, anchor='center')

        label = tk.Label(container, text=self.message, fg='white', bg='black', font=('Segoe UI', 24))
        label.pack(pady=12)
        sub = tk.Label(container, text='Press Ctrl+Alt+U to unlock', fg='#cccccc', bg='black', font=('Segoe UI', 14))
        sub.pack(pady=8)

        # grab focus
        try:
            w.focus_force()
        except Exception:
            pass

        self.windows.append(w)

    def _bind_hotkeys(self):
        if not self.root:
            return
        # Bind common patterns to be robust on Windows/Tk
        self.root.bind_all('<Control-Alt-KeyPress-u>', self._on_hotkey)
        self.root.bind_all('<Control-Alt-KeyPress-U>', self._on_hotkey)
        self.root.bind_all('<Control-KeyPress-Alt_L>', lambda e: None)  # no-op to keep Alt state

        # Keep refocusing so one of our windows has focus
        def refocus_all():
            for w in self.windows:
                try:
                    w.lift()
                    w.focus_force()
                except Exception:
                    pass
            self.root.after(800, refocus_all)
        self.root.after(800, refocus_all)

    def _on_hotkey(self, event=None):
        # Show password prompt on the primary window only
        primary = self.root or (self.windows[0] if self.windows else None)
        if primary is None:
            return
        pwd = simpledialog.askstring('Unlock', 'Enter password:', show='*', parent=primary)
        if pwd is None:
            return
        try:
            cfg = load_config()
            if verify_password(cfg, pwd):
                self.password_unlocked.set()
            else:
                messagebox.showerror('Unlock failed', 'Incorrect password.', parent=primary)
        finally:
            pwd = None

    def run(self):
        # Create fullscreen windows for each monitor
        monitors = sorted(get_monitors(), key=lambda m: (m.is_primary is False, m.x, m.y))
        for i, m in enumerate(monitors):
            self._build_window_for_monitor(m, is_primary=(i == 0))

        self._bind_hotkeys()

        # Main loop on primary
        primary = self.root or (self.windows[0] if self.windows else None)

        def check_unlock():
            if self.password_unlocked.is_set():
                # Signal unlock by switching back to Default desktop
                try:
                    hdef = desktop.open_desktop(desktop.DEFAULT_DESKTOP)
                    desktop.switch_desktop(hdef)
                    desktop.close_desktop(hdef)
                except Exception as e:
                    # Best effort; still exit
                    sys.stderr.write(f"Unlock switch error: {e}\n")
                finally:
                    for w in self.windows:
                        try:
                            w.destroy()
                        except Exception:
                            pass
                    if self.root:
                        try:
                            self.root.destroy()
                        except Exception:
                            pass
                    # Exit process
                    os._exit(0)
            else:
                if primary is not None:
                    primary.after(200, check_unlock)

        if primary is not None:
            primary.after(200, check_unlock)
            # Run a single mainloop in the main thread
            primary.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--desktop-name', default=desktop.LOCK_DESKTOP)
    args = ap.parse_args()

    # Attach to lock desktop and make it active
    hdesk = desktop.open_desktop(args.desktop_name)
    try:
        # Must set thread desktop before any windows are created
        desktop.set_thread_desktop(hdesk)
        desktop.switch_desktop(hdesk)
    finally:
        # Keep our handle open while running; will be closed on exit
        pass

    cfg = load_config()
    hotkey = cfg.get('hotkey', 'ctrl+alt+u')
    LockScreen(hotkey).run()


if __name__ == '__main__':
    main()
