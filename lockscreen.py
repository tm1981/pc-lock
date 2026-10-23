import argparse
import ctypes
import os
import sys
import time

import tkinter as tk

from screeninfo import get_monitors

import desktop
from config import load_config as _load_config, verify_password as _verify

# Exit codes understood by Locker._watch_child: 0 = unlocked with password, anything else = respawn
EXIT_UNLOCKED = 0
EXIT_UNEXPECTED = 3

BG = '#0b0f19'
FG = '#e5e7eb'
MUTED = '#6b7280'
ERROR = '#f87171'

PANEL_IDLE_SECONDS = 30
MAX_FAILS_BEFORE_LOCKOUT = 5
LOCKOUT_SECONDS = 30


def hotkey_to_tk(hotkey: str) -> list[str]:
    """'ctrl+alt+u' -> ['<Control-Alt-KeyPress-u>', '<Control-Alt-KeyPress-U>']"""
    mods = {'ctrl': 'Control', 'control': 'Control', 'alt': 'Alt', 'shift': 'Shift'}
    parts = [p.strip() for p in hotkey.replace('-', '+').split('+') if p.strip()]
    key = parts[-1] if parts else 'u'
    prefix = ''.join(f'{mods[p.lower()]}-' for p in parts[:-1] if p.lower() in mods)
    if len(key) == 1 and key.isalpha():
        return [f'<{prefix}KeyPress-{key.lower()}>', f'<{prefix}KeyPress-{key.upper()}>']
    if key.lower().startswith('f') and key[1:].isdigit():
        key = key.upper()  # Tk keysyms are case-sensitive: F12
    return [f'<{prefix}KeyPress-{key}>']


def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class LockScreen:
    def __init__(self, hotkey: str, message: str = 'This desktop is locked.'):
        self.hotkey = hotkey
        self.message = message
        self.root: tk.Tk | None = None
        self.windows: list[tk.Misc] = []
        self.clock_labels: list[tk.Label] = []
        self.panel: tk.Frame | None = None
        self.entry: tk.Entry | None = None
        self.feedback: tk.Label | None = None
        self.panel_visible = False
        self.last_activity = 0.0
        self.fails = 0
        self.lockout_until = 0.0
        self.lockout_count = 0

    def _build_window_for_monitor(self, m, is_primary: bool = False):
        if is_primary:
            w = tk.Tk()
            self.root = w
        else:
            w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
        w.configure(bg=BG, cursor='none')
        # Alt+F4 / close requests must never end the lock
        w.protocol('WM_DELETE_WINDOW', lambda: None)
        w.bind('<Alt-F4>', lambda e: 'break')

        container = tk.Frame(w, bg=BG)
        container.place(relx=0.5, rely=0.42, anchor='center')

        clock = tk.Label(container, text='', fg=FG, bg=BG, font=('Segoe UI Light', 72))
        clock.pack()
        self.clock_labels.append(clock)
        tk.Label(container, text=self.message, fg=FG, bg=BG, font=('Segoe UI', 22)).pack(pady=(4, 0))

        if is_primary:
            self._build_password_panel(container)

        self.windows.append(w)

    def _build_password_panel(self, parent):
        self.panel = tk.Frame(parent, bg=BG)
        tk.Label(self.panel, text='Enter password to unlock', fg=MUTED, bg=BG,
                 font=('Segoe UI', 13)).pack(pady=(28, 8))
        self.entry = tk.Entry(self.panel, show='•', width=24, font=('Segoe UI', 18), justify='center',
                              bg='#1f2937', fg=FG, insertbackground=FG, relief='flat',
                              highlightthickness=2, highlightbackground='#374151', highlightcolor='#3b82f6')
        self.entry.pack(ipady=6)
        self.entry.bind('<Return>', self._on_submit)
        self.entry.bind('<Escape>', lambda e: self._hide_panel())
        self.entry.bind('<Key>', lambda e: self._touch())
        self.feedback = tk.Label(self.panel, text='', fg=ERROR, bg=BG, font=('Segoe UI', 12))
        self.feedback.pack(pady=(8, 0))

    def _touch(self):
        self.last_activity = time.monotonic()

    def _show_panel(self, event=None):
        if not self.panel:
            return
        if not self.panel_visible:
            self.panel.pack()
            self.panel_visible = True
        self.feedback.configure(text='', fg=ERROR)
        self.entry.delete(0, 'end')
        self.entry.focus_force()
        self._touch()

    def _hide_panel(self):
        if self.panel and self.panel_visible:
            self.entry.delete(0, 'end')
            self.panel.pack_forget()
            self.panel_visible = False

    def _on_submit(self, event=None):
        now = time.monotonic()
        if now < self.lockout_until:
            return
        pwd = self.entry.get()
        self.entry.delete(0, 'end')
        # Fail closed: a missing/corrupt config never unlocks (Ctrl+Alt+Del -> sign out still works)
        if pwd and _verify(pwd):
            self._unlock()
            return
        self.fails += 1
        if self.fails >= MAX_FAILS_BEFORE_LOCKOUT:
            self.fails = 0
            self.lockout_count += 1
            self.lockout_until = now + LOCKOUT_SECONDS * self.lockout_count
            self.entry.configure(state='disabled')
        else:
            self.feedback.configure(text='Incorrect password')
        self._touch()

    def _unlock(self):
        try:
            hdef = desktop.open_desktop(desktop.DEFAULT_DESKTOP)
            desktop.switch_desktop(hdef)
            desktop.close_desktop(hdef)
        except Exception as e:
            sys.stderr.write(f"Unlock switch error: {e}\n")
        os._exit(EXIT_UNLOCKED)

    def _bind_hotkeys(self):
        for seq in hotkey_to_tk(self.hotkey):
            self.root.bind_all(seq, self._show_panel)

    def _tick(self):
        now = time.monotonic()
        clock_text = time.strftime('%H:%M')
        for lbl in self.clock_labels:
            if lbl.cget('text') != clock_text:
                lbl.configure(text=clock_text)
        if self.panel_visible:
            if now < self.lockout_until:
                self.feedback.configure(text=f'Too many attempts. Try again in {int(self.lockout_until - now) + 1}s')
            elif str(self.entry.cget('state')) == 'disabled':
                self.entry.configure(state='normal')
                self.feedback.configure(text='')
                self.entry.focus_force()
            elif now - self.last_activity > PANEL_IDLE_SECONDS:
                self._hide_panel()
        self.root.after(250, self._tick)

    def _refocus(self):
        # Keep our windows on top and holding keyboard focus so the hotkey always works
        for w in self.windows:
            try:
                w.lift()
            except Exception:
                pass
        try:
            if self.panel_visible and str(self.entry.cget('state')) == 'normal':
                self.entry.focus_force()
            else:
                self.root.focus_force()
        except Exception:
            pass
        self.root.after(800, self._refocus)

    def run(self):
        monitors = sorted(get_monitors(), key=lambda m: (not m.is_primary, m.x, m.y))
        for i, m in enumerate(monitors):
            self._build_window_for_monitor(m, is_primary=(i == 0))
        self._bind_hotkeys()
        self.root.after(0, self._tick)
        self.root.after(300, self._refocus)
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--desktop-name', default=desktop.LOCK_DESKTOP)
    ap.add_argument('--reason', choices=['manual', 'schedule'], default='manual')
    ap.add_argument('--start')
    ap.add_argument('--end')
    args = ap.parse_args()

    _enable_dpi_awareness()

    # Attach to lock desktop and make it active. Must happen before any window is created.
    hdesk = desktop.open_desktop(args.desktop_name)
    desktop.set_thread_desktop(hdesk)
    desktop.switch_desktop(hdesk)

    cfg = _load_config()
    hotkey = cfg.get('hotkey', 'ctrl+alt+u')
    if args.reason == 'schedule' and args.start and args.end:
        msg = f'Locked by schedule ({args.start}–{args.end})'
    elif args.reason == 'manual':
        msg = 'This desktop is locked'
    else:
        msg = 'This desktop is locked.'
    try:
        LockScreen(hotkey, message=msg).run()
    finally:
        # mainloop only returns if the windows were destroyed some other way: not an unlock
        os._exit(EXIT_UNEXPECTED)


if __name__ == '__main__':
    main()
