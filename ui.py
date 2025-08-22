import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from config import load_config

# System tray
from PIL import ImageDraw
import pystray

# Reuse the Locker and helpers from main.py
import main as core
from api import maybe_start_api
from config import load_config, save_config, verify_password, set_password, update_api


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
                from schedule_store import read_schedule
                sched = read_schedule()
                enabled = bool(sched.get('enabled', False))
                if enabled:
                    try:
                        start = dtime.fromisoformat(sched.get('start', '22:00'))
                        end = dtime.fromisoformat(sched.get('end', '07:00'))
                        should_lock = in_lock_window(datetime.now(), start, end)
                        if should_lock and not self.locker.state.active:
                            self.locker.lock_now(reason='schedule', start=start.isoformat(timespec='minutes'), end=end.isoformat(timespec='minutes'))
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
        # Try load packaged icon first
        try:
            import sys, os
            ico_path = None
            if getattr(sys, 'frozen', False):
                base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
                candidate = os.path.join(base, 'assets', 'pclock.ico')
                if os.path.exists(candidate):
                    ico_path = candidate
            else:
                from pathlib import Path
                candidate = Path(__file__).with_name('assets') / 'pclock.ico'
                if candidate.exists():
                    ico_path = str(candidate)
            if ico_path:
                from PIL import Image
                return Image.open(ico_path)
        except Exception:
            pass
        # Fallback: draw a simple vector icon
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
        # Internal flags
        self._loading = False
        self._schedule_dirty = False

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
        # Track unsaved changes to prevent tick() from overwriting user edits
        self.enabled_var.trace_add('write', self._on_schedule_field_changed)
        self.start_var.trace_add('write', self._on_schedule_field_changed)
        self.end_var.trace_add('write', self._on_schedule_field_changed)
        ttk.Label(frm_sched, text='Start (HH:MM)').grid(row=1, column=0, sticky='w', **pad)
        ttk.Entry(frm_sched, textvariable=self.start_var, width=10).grid(row=1, column=1, sticky='w', **pad)
        ttk.Label(frm_sched, text='End (HH:MM)').grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm_sched, textvariable=self.end_var, width=10).grid(row=2, column=1, sticky='w', **pad)
        ttk.Button(frm_sched, text='Save schedule', command=self.on_save_schedule).grid(row=3, column=0, columnspan=2, sticky='e', **pad)

        frm_api = ttk.LabelFrame(root, text='API')
        frm_api.pack(fill='x', **pad)
        self.api_enabled_var = tk.BooleanVar(value=False)
        self.api_host_var = tk.StringVar(value='127.0.0.1')
        self.api_port_var = tk.StringVar(value='8765')
        ttk.Checkbutton(frm_api, text='Enable REST API', variable=self.api_enabled_var).grid(row=0, column=0, sticky='w', **pad)
        ttk.Label(frm_api, text='Host').grid(row=1, column=0, sticky='w', **pad)
        ttk.Entry(frm_api, textvariable=self.api_host_var, width=16).grid(row=1, column=1, sticky='w', **pad)
        ttk.Label(frm_api, text='Port').grid(row=2, column=0, sticky='w', **pad)
        ttk.Entry(frm_api, textvariable=self.api_port_var, width=8).grid(row=2, column=1, sticky='w', **pad)
        ttk.Button(frm_api, text='Save API', command=self.on_save_api).grid(row=3, column=0, columnspan=2, sticky='e', **pad)

        frm_pw = ttk.LabelFrame(root, text='Password')
        frm_pw.pack(fill='x', **pad)
        ttk.Button(frm_pw, text='Change password', command=self.on_change_password).pack(anchor='e', **pad)

        # Load initial config
        self.load_into_ui()

        # If password not set, force setup
        self.ensure_password_set()

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
            self._loading = True
            from schedule_store import read_schedule
            sched = read_schedule()
            self.enabled_var.set(bool(sched.get('enabled', False)))
            self.start_var.set(sched.get('start', '22:00'))
            self.end_var.set(sched.get('end', '07:00'))
            # API
            cfg = load_config()
            api = cfg.get('api', {})
            self.api_enabled_var.set(bool(api.get('enabled', False)))
            self.api_host_var.set(str(api.get('host', '127.0.0.1')))
            self.api_port_var.set(str(api.get('port', 8765)))
        except Exception:
            pass
        finally:
            self._loading = False
            self._schedule_dirty = False

    def on_lock_now(self):
        try:
            self.locker.lock_now(reason='manual')
            self.update_status(True)
        except Exception as e:
            messagebox.showerror('Error', f'Failed to lock: {e}')

    def on_save_schedule(self):
        try:
            # Require current password to save schedule
            pw = simpledialog.askstring('Confirm', 'Enter password to save schedule:', show='*', parent=self.root)
            if pw is None or not verify_password(pw):
                messagebox.showerror('Error', 'Incorrect password. Schedule not saved.')
                return
            # validate times
            start = dtime.fromisoformat(self.start_var.get())
            end = dtime.fromisoformat(self.end_var.get())
            # Persist securely (DPAPI)
            from schedule_store import write_schedule
            write_schedule(bool(self.enabled_var.get()), start.isoformat(timespec='minutes'), end.isoformat(timespec='minutes'))
            messagebox.showinfo('Saved', 'Schedule updated.')
            self._schedule_dirty = False
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
        try:
            set_password(new_pw)
            messagebox.showinfo('Success', 'Password changed.')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to change password: {e}')

    def lock_if_in_schedule_now(self):
        try:
            from schedule_store import read_schedule
            sched = read_schedule()
            if not bool(sched.get('enabled', False)):
                return
            start = dtime.fromisoformat(sched.get('start', '22:00'))
            end = dtime.fromisoformat(sched.get('end', '07:00'))
            if in_lock_window(datetime.now(), start, end):
                self.locker.lock_now(reason='schedule', start=start.isoformat(timespec='minutes'), end=end.isoformat(timespec='minutes'))
                self.update_status(True)
        except Exception:
            pass

    def on_save_api(self):
        try:
            # Require current password to change API settings
            pw = simpledialog.askstring('Confirm', 'Enter password to save API settings:', show='*', parent=self.root)
            if pw is None or not verify_password(pw):
                messagebox.showerror('Error', 'Incorrect password. API settings not saved.')
                return
            enabled = bool(self.api_enabled_var.get())
            host = self.api_host_var.get().strip() or '127.0.0.1'
            port = int(self.api_port_var.get().strip() or '8765')
            update_api(enabled, host, port)
            # restart server if needed
            if self.api_server:
                try:
                    self.api_server.stop()
                except Exception:
                    pass
                self.api_server = None
            self.api_server = maybe_start_api(self.locker)
            messagebox.showinfo('Saved', 'API settings updated.')
        except Exception as e:
            messagebox.showerror('Error', f'Invalid API settings: {e}')

    def ensure_password_set(self):
        try:
            cfg = load_config()
            pwcfg = cfg.get('password', {})
            if not pwcfg.get('salt') or not pwcfg.get('hash'):
                while True:
                    new_pw = simpledialog.askstring('Set password', 'Create a new unlock password:', show='*', parent=self.root)
                    if new_pw is None:
                        messagebox.showerror('Required', 'A password is required on first run.')
                        continue
                    if len(new_pw) < 4:
                        messagebox.showerror('Error', 'Password must be at least 4 characters.')
                        continue
                    confirm = simpledialog.askstring('Set password', 'Confirm password:', show='*', parent=self.root)
                    if confirm != new_pw:
                        messagebox.showerror('Error', 'Passwords do not match.')
                        continue
                    set_password(new_pw)
                    messagebox.showinfo('Success', 'Password set.')
                    break
        except Exception:
            pass

    def tick(self):
        self.update_status()
        # Sync schedule UI with secure store (handles external changes like auto-disable on unlock)
        if not self._schedule_dirty:
            try:
                self._loading = True
                from schedule_store import read_schedule
                sched = read_schedule()
                enabled = bool(sched.get('enabled', False))
                if self.enabled_var.get() != enabled:
                    self.enabled_var.set(enabled)
                # Optionally sync times too
                if self.start_var.get() != sched.get('start', '22:00'):
                    self.start_var.set(sched.get('start', '22:00'))
                if self.end_var.get() != sched.get('end', '07:00'):
                    self.end_var.set(sched.get('end', '07:00'))
            except Exception:
                pass
            finally:
                self._loading = False
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

    def _on_schedule_field_changed(self, *args):
        if self._loading:
            return
        self._schedule_dirty = True


if __name__ == '__main__':
    root = tk.Tk()
    app = AppUI(root)
    root.mainloop()
