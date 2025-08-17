import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from secrets import token_bytes
from hashlib import pbkdf2_hmac

# System tray
from PIL import Image, ImageDraw
import pystray

# Reuse the Locker and helpers from main.py
import main as core
from api import maybe_start_api

CONFIG_PATH = Path(__file__).with_name('config.json')


def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def verify_password(password: str) -> bool:
    cfg = load_config()
    pwcfg = cfg.get('password', {})
    salt_hex = pwcfg.get('salt')
    hash_hex = pwcfg.get('hash')
    iterations = int(pwcfg.get('iterations', 200_000))
    if not salt_hex or not hash_hex:
        return False
    salt = bytes.fromhex(salt_hex)
    calc = pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return calc.hex() == hash_hex


def set_password(old_pw: str, new_pw: str) -> bool:
    if not verify_password(old_pw):
        return False
    cfg = load_config()
    salt = token_bytes(16)
    iter_cnt = int(cfg.get('password', {}).get('iterations', 200_000))
    new_hash = pbkdf2_hmac('sha256', new_pw.encode('utf-8'), salt, iter_cnt).hex()
    cfg.setdefault('password', {})['salt'] = salt.hex()
    cfg['password']['hash'] = new_hash
    cfg['password']['iterations'] = iter_cnt
    cfg['password']['algo'] = 'pbkdf2_sha256'
    save_config(cfg)
    return True


def in_lock_window(now: datetime, start: dtime, end: dtime) -> bool:
    return core.in_lock_window(now, start, end)


class SchedulerThread(threading.Thread):
    def __init__(self, locker: core.Locker, on_state_change=None):
        super().__init__(daemon=True)
        self.locker = locker
        self.on_state_change = on_state_change
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                cfg = load_config()
                sched = cfg.get('schedule', {})
                enabled = bool(sched.get('enabled', False))
                if enabled:
                    try:
                        start = dtime.fromisoformat(sched.get('start', '22:00'))
                        end = dtime.fromisoformat(sched.get('end', '07:00'))
                        should_lock = in_lock_window(datetime.now(), start, end)
                        if should_lock and not self.locker.state.active:
                            self.locker.lock_now()
                            if self.on_state_change:
                                self.on_state_change(True)
                        elif not should_lock and self.locker.state.active:
                            self.locker.unlock_now()
                            if self.on_state_change:
                                self.on_state_change(False)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(1)


class TrayManager:
    def __init__(self, app: 'AppUI'):
        self.app = app
        self.icon = pystray.Icon('pc-lock', self._build_icon(), 'PC Lock', menu=pystray.Menu(
            pystray.MenuItem('Open', self.on_open),
            pystray.MenuItem('Lock now', self.on_lock),
            pystray.MenuItem('Exit', self.on_exit)
        ))
        self.thread = threading.Thread(target=self.icon.run, daemon=True)

    def _build_icon(self):
        # Create a simple lock icon
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # body
        d.rectangle([16, 28, 48, 50], fill=(0, 0, 0, 255))
        # shackle
        d.arc([14, 6, 50, 42], start=200, end=-20, fill=(0, 0, 0, 255), width=6)
        return img

    def start(self):
        if not self.thread.is_alive():
            self.thread.start()

    def show(self):
        self.icon.visible = True

    def hide(self):
        self.icon.visible = False

    def on_open(self, icon, item):
        self.app.show_window()

    def on_lock(self, icon, item):
        self.app.root.after(0, self.app.on_lock_now)

    def on_exit(self, icon, item):
        # password-protected exit
        def prompt_and_exit():
            pw = simpledialog.askstring('Exit PC Lock', 'Enter password to exit:', show='*', parent=self.app.root)
            if pw and verify_password(pw):
                try:
                    self.app.scheduler.stop()
                except Exception:
                    pass
                self.icon.visible = False
                self.icon.stop()
                self.app.root.destroy()
            else:
                messagebox.showerror('Error', 'Incorrect password.')
        self.app.root.after(0, prompt_and_exit)


class AppUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('PC Lock')
        self.root.geometry('360x260')
        self.locker = core.Locker()
        self.status_var = tk.StringVar(value='Status: Unlocked')

        # UI layout
        pad = {'padx': 10, 'pady': 6}
        frm_top = ttk.Frame(root)
        frm_top.pack(fill='x', **pad)
        ttk.Label(frm_top, textvariable=self.status_var).pack(side='left')
        ttk.Button(frm_top, text='Lock now', command=self.on_lock_now).pack(side='right')

        frm_sched = ttk.LabelFrame(root, text='Schedule')
        frm_sched.pack(fill='x', **pad)
        self.enabled_var = tk.BooleanVar(value=False)
        self.start_var = tk.StringVar(value='22:00')
        self.end_var = tk.StringVar(value='07:00')
        ttk.Checkbutton(frm_sched, text='Enabled', variable=self.enabled_var).grid(row=0, column=0, sticky='w', **pad)
        ttk.Label(frm_sched, text='Start (HH:MM)').grid(row=1, column=0, sticky='w', **pad)
        ttk.Entry(frm_sched, textvariable=self.start_var, width=10).grid(row=1, column=1, sticky='w', **pad)
        ttk.Label(frm_sched, text='End (HH:MM)').grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm_sched, textvariable=self.end_var, width=10).grid(row=2, column=1, sticky='w', **pad)
        ttk.Button(frm_sched, text='Save schedule', command=self.on_save_schedule).grid(row=3, column=0, columnspan=2, sticky='e', **pad)

        frm_pw = ttk.LabelFrame(root, text='Password')
        frm_pw.pack(fill='x', **pad)
        ttk.Button(frm_pw, text='Change password', command=self.on_change_password).pack(anchor='e', **pad)

        # Load initial config
        self.load_into_ui()

        # Start scheduler thread
        self.scheduler = SchedulerThread(self.locker, on_state_change=self.update_status)
        self.scheduler.start()

        # Also check if we should lock immediately given schedule
        self.lock_if_in_schedule_now()

        # Update status periodically
        self.tick()

        # Tray
        self.tray = TrayManager(self)
        self.tray.start()

        # Start REST API if enabled in config
        self.api_server = maybe_start_api(self.locker)

        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)

    def update_status(self, locked: bool | None = None):
        if locked is None:
            locked = self.locker.state.active
        self.status_var.set('Status: Locked' if locked else 'Status: Unlocked')

    def load_into_ui(self):
        try:
            cfg = load_config()
            sched = cfg.get('schedule', {})
            self.enabled_var.set(bool(sched.get('enabled', False)))
            self.start_var.set(sched.get('start', '22:00'))
            self.end_var.set(sched.get('end', '07:00'))
        except Exception:
            pass

    def on_lock_now(self):
        try:
            self.locker.lock_now()
            self.update_status(True)
        except Exception as e:
            messagebox.showerror('Error', f'Failed to lock: {e}')

    def on_save_schedule(self):
        try:
            # validate times
            start = dtime.fromisoformat(self.start_var.get())
            end = dtime.fromisoformat(self.end_var.get())
            cfg = load_config()
            cfg.setdefault('schedule', {})['enabled'] = bool(self.enabled_var.get())
            cfg['schedule']['start'] = start.isoformat(timespec='minutes')
            cfg['schedule']['end'] = end.isoformat(timespec='minutes')
            save_config(cfg)
            messagebox.showinfo('Saved', 'Schedule updated.')
            # Optionally re-evaluate now
            self.lock_if_in_schedule_now()
        except Exception as e:
            messagebox.showerror('Error', f'Invalid schedule: {e}')

    def on_change_password(self):
        old_pw = simpledialog.askstring('Change password', 'Enter current password:', show='*', parent=self.root)
        if old_pw is None:
            return
        if not verify_password(old_pw):
            messagebox.showerror('Error', 'Current password is incorrect.')
            return
        new_pw = simpledialog.askstring('Change password', 'Enter new password:', show='*', parent=self.root)
        if new_pw is None or len(new_pw) < 4:
            messagebox.showerror('Error', 'Password must be at least 4 characters.')
            return
        confirm = simpledialog.askstring('Change password', 'Confirm new password:', show='*', parent=self.root)
        if confirm != new_pw:
            messagebox.showerror('Error', 'Passwords do not match.')
            return
        if set_password(old_pw, new_pw):
            messagebox.showinfo('Success', 'Password changed.')
        else:
            messagebox.showerror('Error', 'Failed to change password.')

    def lock_if_in_schedule_now(self):
        try:
            cfg = load_config()
            sched = cfg.get('schedule', {})
            if not bool(sched.get('enabled', False)):
                return
            start = dtime.fromisoformat(sched.get('start', '22:00'))
            end = dtime.fromisoformat(sched.get('end', '07:00'))
            if in_lock_window(datetime.now(), start, end):
                self.locker.lock_now()
                self.update_status(True)
        except Exception:
            pass

    def tick(self):
        self.update_status()
        self.root.after(1000, self.tick)

    def minimize_to_tray(self):
        try:
            self.root.withdraw()
            self.tray.show()
            self.root.after(100, lambda: None)
        except Exception:
            pass

    def show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.tray.hide()
        except Exception:
            pass


if __name__ == '__main__':
    root = tk.Tk()
    app = AppUI(root)
    root.mainloop()
