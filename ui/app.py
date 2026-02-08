"""
Main application UI for PC-Lock.
"""
from datetime import datetime, time as dtime
from tkinter import messagebox

import customtkinter as ctk

import main as core
from api import maybe_start_api
from config import load_config, verify_password, set_password, update_api

from .dialogs import ask_password
from .scheduler import SchedulerThread, in_lock_window
from .tray import TrayManager


class AppUI:
    """Modern CustomTkinter-based main application."""

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title('PC Lock')
        self.root.geometry('420x680')
        self.root.minsize(400, 650)

        self.locker = core.Locker()
        self._loading = False
        self._schedule_dirty = False

        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._build_ui()
        self.load_into_ui()
        self.ensure_password_set()

        # Start scheduler
        self.scheduler = SchedulerThread(self.locker, on_state_change=self.update_status)
        self.scheduler.start()

        # Check if we should lock immediately
        self.lock_if_in_schedule_now()

        # Status update timer
        self.tick()

        # System tray
        self.tray = TrayManager(self)
        self.tray.start()

        # Start API if enabled
        self.api_server = maybe_start_api(self.locker)

        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)

    def _build_ui(self):
        # Main container with padding
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Status section
        status_frame = ctk.CTkFrame(main)
        status_frame.pack(fill="x", pady=(0, 15))

        self.status_indicator = ctk.CTkLabel(
            status_frame,
            text="●",
            font=ctk.CTkFont(size=24),
            text_color="#22c55e"  # Green
        )
        self.status_indicator.pack(side="left", padx=15, pady=15)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="Unlocked",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.status_label.pack(side="left", pady=15)

        self.lock_btn = ctk.CTkButton(
            status_frame,
            text="Lock Now",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=120,
            height=40,
            command=self.on_lock_now
        )
        self.lock_btn.pack(side="right", padx=15, pady=15)

        # Schedule section
        sched_frame = ctk.CTkFrame(main)
        sched_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            sched_frame,
            text="Schedule",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Enable checkbox
        self.enabled_var = ctk.BooleanVar(value=False)
        self.enabled_cb = ctk.CTkCheckBox(
            sched_frame,
            text="Enable scheduled lock",
            variable=self.enabled_var,
            font=ctk.CTkFont(size=14),
            command=self._on_schedule_changed
        )
        self.enabled_cb.pack(anchor="w", padx=15, pady=5)

        # Time inputs row
        time_frame = ctk.CTkFrame(sched_frame, fg_color="transparent")
        time_frame.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(time_frame, text="Start:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.start_var = ctk.StringVar(value="22:00")
        self.start_entry = ctk.CTkEntry(
            time_frame,
            textvariable=self.start_var,
            width=80,
            font=ctk.CTkFont(size=14),
            justify="center"
        )
        self.start_entry.pack(side="left", padx=(5, 20))
        self.start_entry.bind("<KeyRelease>", lambda e: self._on_schedule_changed())

        ctk.CTkLabel(time_frame, text="End:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.end_var = ctk.StringVar(value="07:00")
        self.end_entry = ctk.CTkEntry(
            time_frame,
            textvariable=self.end_var,
            width=80,
            font=ctk.CTkFont(size=14),
            justify="center"
        )
        self.end_entry.pack(side="left", padx=5)
        self.end_entry.bind("<KeyRelease>", lambda e: self._on_schedule_changed())

        # Save schedule button
        self.save_sched_btn = ctk.CTkButton(
            sched_frame,
            text="Save Schedule",
            font=ctk.CTkFont(size=14),
            command=self.on_save_schedule
        )
        self.save_sched_btn.pack(anchor="e", padx=15, pady=(5, 15))

        # API section
        api_frame = ctk.CTkFrame(main)
        api_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            api_frame,
            text="REST API",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        self.api_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            api_frame,
            text="Enable API server",
            variable=self.api_enabled_var,
            font=ctk.CTkFont(size=14)
        ).pack(anchor="w", padx=15, pady=5)

        api_row = ctk.CTkFrame(api_frame, fg_color="transparent")
        api_row.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(api_row, text="Host:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.api_host_var = ctk.StringVar(value="127.0.0.1")
        ctk.CTkEntry(api_row, textvariable=self.api_host_var, width=120,
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=(5, 15))

        ctk.CTkLabel(api_row, text="Port:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.api_port_var = ctk.StringVar(value="8765")
        ctk.CTkEntry(api_row, textvariable=self.api_port_var, width=70,
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=5)

        ctk.CTkButton(
            api_frame,
            text="Save API",
            font=ctk.CTkFont(size=14),
            command=self.on_save_api
        ).pack(anchor="e", padx=15, pady=(5, 15))

        # Password section
        pw_frame = ctk.CTkFrame(main)
        pw_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            pw_frame,
            text="Security",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))

        ctk.CTkButton(
            pw_frame,
            text="Change Password",
            font=ctk.CTkFont(size=14),
            fg_color="gray40",
            hover_color="gray30",
            command=self.on_change_password
        ).pack(anchor="e", padx=15, pady=(5, 15))

        # Appearance toggle
        appear_frame = ctk.CTkFrame(main, fg_color="transparent")
        appear_frame.pack(fill="x")

        ctk.CTkLabel(
            appear_frame,
            text="Theme:",
            font=ctk.CTkFont(size=12)
        ).pack(side="left")

        self.appearance_menu = ctk.CTkOptionMenu(
            appear_frame,
            values=["Dark", "Light", "System"],
            command=self._change_appearance,
            width=100,
            font=ctk.CTkFont(size=12)
        )
        self.appearance_menu.pack(side="left", padx=10)
        self.appearance_menu.set("Dark")

    def _change_appearance(self, mode: str):
        ctk.set_appearance_mode(mode.lower())

    def _on_schedule_changed(self):
        if not self._loading:
            self._schedule_dirty = True

    def update_status(self, locked: bool = None):
        if locked is None:
            locked = self.locker.state.active

        if locked:
            self.status_label.configure(text="Locked")
            self.status_indicator.configure(text_color="#ef4444")  # Red
            self.lock_btn.configure(state="disabled")
        else:
            self.status_label.configure(text="Unlocked")
            self.status_indicator.configure(text_color="#22c55e")  # Green
            self.lock_btn.configure(state="normal")

    def load_into_ui(self):
        try:
            self._loading = True
            from schedule_store import read_schedule
            sched = read_schedule()
            self.enabled_var.set(bool(sched.get('enabled', False)))
            self.start_var.set(sched.get('start', '22:00'))
            self.end_var.set(sched.get('end', '07:00'))

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
            pw = ask_password(self.root, 'Confirm', 'Enter password to save schedule:')
            if pw is None or not verify_password(pw):
                if pw is not None:
                    messagebox.showerror('Error', 'Incorrect password.')
                return

            start = dtime.fromisoformat(self.start_var.get())
            end = dtime.fromisoformat(self.end_var.get())

            from schedule_store import write_schedule
            write_schedule(
                bool(self.enabled_var.get()),
                start.isoformat(timespec='minutes'),
                end.isoformat(timespec='minutes')
            )
            messagebox.showinfo('Saved', 'Schedule updated.')
            self._schedule_dirty = False
            self.lock_if_in_schedule_now()
        except Exception as e:
            messagebox.showerror('Error', f'Invalid schedule: {e}')

    def on_save_api(self):
        try:
            pw = ask_password(self.root, 'Confirm', 'Enter password to save API settings:')
            if pw is None or not verify_password(pw):
                if pw is not None:
                    messagebox.showerror('Error', 'Incorrect password.')
                return

            enabled = bool(self.api_enabled_var.get())
            host = self.api_host_var.get().strip() or '127.0.0.1'
            port = int(self.api_port_var.get().strip() or '8765')
            update_api(enabled, host, port)

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

    def on_change_password(self):
        old_pw = ask_password(self.root, 'Change Password', 'Enter current password:')
        if old_pw is None:
            return
        if not verify_password(old_pw):
            messagebox.showerror('Error', 'Current password is incorrect.')
            return

        new_pw = ask_password(self.root, 'Change Password', 'Enter new password:')
        if new_pw is None or len(new_pw) < 4:
            messagebox.showerror('Error', 'Password must be at least 4 characters.')
            return

        confirm = ask_password(self.root, 'Change Password', 'Confirm new password:')
        if confirm != new_pw:
            messagebox.showerror('Error', 'Passwords do not match.')
            return

        try:
            set_password(new_pw)
            messagebox.showinfo('Success', 'Password changed.')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to change password: {e}')

    def ensure_password_set(self):
        try:
            cfg = load_config()
            pwcfg = cfg.get('password', {})
            if not pwcfg.get('salt') or not pwcfg.get('hash'):
                while True:
                    new_pw = ask_password(self.root, 'Set Password', 'Create a new unlock password:')
                    if new_pw is None:
                        messagebox.showerror('Required', 'A password is required on first run.')
                        continue
                    if len(new_pw) < 4:
                        messagebox.showerror('Error', 'Password must be at least 4 characters.')
                        continue

                    confirm = ask_password(self.root, 'Set Password', 'Confirm password:')
                    if confirm != new_pw:
                        messagebox.showerror('Error', 'Passwords do not match.')
                        continue

                    set_password(new_pw)
                    messagebox.showinfo('Success', 'Password set.')
                    break
        except Exception:
            pass

    def lock_if_in_schedule_now(self):
        try:
            from schedule_store import read_schedule
            sched = read_schedule()
            if not bool(sched.get('enabled', False)):
                return
            start = dtime.fromisoformat(sched.get('start', '22:00'))
            end = dtime.fromisoformat(sched.get('end', '07:00'))
            if in_lock_window(datetime.now(), start, end):
                self.locker.lock_now(
                    reason='schedule',
                    start=start.isoformat(timespec='minutes'),
                    end=end.isoformat(timespec='minutes')
                )
                self.update_status(True)
        except Exception:
            pass

    def tick(self):
        self.update_status()

        if not self._schedule_dirty:
            try:
                self._loading = True
                from schedule_store import read_schedule
                sched = read_schedule()
                enabled = bool(sched.get('enabled', False))
                if self.enabled_var.get() != enabled:
                    self.enabled_var.set(enabled)
            except Exception:
                pass
            finally:
                self._loading = False

        self.root.after(1000, self.tick)

    def minimize_to_tray(self):
        try:
            self.root.withdraw()
            self.tray.show()
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


def main():
    root = ctk.CTk()
    app = AppUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
