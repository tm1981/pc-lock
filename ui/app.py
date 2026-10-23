"""
Main application UI for PC-Lock.
"""
import queue
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

import main as core
import single_instance
from api import maybe_start_api
from config import load_config, verify_password, set_password, update_api, has_password
from scheduler import SchedulerThread, parse_hhmm, fmt_hhmm, is_snoozed
from schedule_store import read_schedule, update_schedule

from .dialogs import ask_password
from .tray import TrayManager

GREEN = "#22c55e"
RED = "#ef4444"
MUTED = ("gray40", "gray60")


class AppUI:
    """Modern CustomTkinter-based main application."""

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title('PC Lock')
        self.root.geometry('440x720')
        self.root.minsize(420, 680)

        self.locker = core.Locker()
        self._actions: queue.Queue = queue.Queue()
        self._loading = False
        self._schedule_dirty = False
        self.api_server = None

        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._build_ui()
        self.load_into_ui()
        if not self.ensure_password_set():
            self.root.after(0, self.root.destroy)
            return

        # Start API if enabled (before the scheduler so a port error is shown on an unlocked screen)
        self._start_api(show_errors=True)

        # Scheduler locks within a second if we're inside the window right now
        self.scheduler = SchedulerThread(self.locker)
        self.scheduler.start()

        # System tray
        self.tray = TrayManager(self)
        self.tray.start()

        self.root.protocol('WM_DELETE_WINDOW', self.minimize_to_tray)
        self.tick()
        self._drain_actions()

    # --- cross-thread hand-off ------------------------------------------------------
    def post(self, fn):
        """Run fn on the Tk thread. Safe to call from any thread (tray, scheduler, API)."""
        self._actions.put(fn)

    def _drain_actions(self):
        try:
            while True:
                fn = self._actions.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print(f'[ui] action failed: {e}')
        except queue.Empty:
            pass
        if single_instance.show_requested():
            self.show_window()
        self.root.after(100, self._drain_actions)

    # --- layout ---------------------------------------------------------------------
    def _section(self, parent, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(15, 10))
        return frame

    def _build_ui(self):
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Status section
        status_frame = ctk.CTkFrame(main)
        status_frame.pack(fill="x", pady=(0, 15))

        self.status_indicator = ctk.CTkLabel(status_frame, text="●", font=ctk.CTkFont(size=24), text_color=GREEN)
        self.status_indicator.pack(side="left", padx=15, pady=15)

        self.status_label = ctk.CTkLabel(status_frame, text="Unlocked", font=ctk.CTkFont(size=18, weight="bold"))
        self.status_label.pack(side="left", pady=15)

        self.lock_btn = ctk.CTkButton(status_frame, text="Lock Now", font=ctk.CTkFont(size=14, weight="bold"),
                                      width=120, height=40, command=self.on_lock_now)
        self.lock_btn.pack(side="right", padx=15, pady=15)

        # Schedule section
        sched_frame = self._section(main, "Schedule")

        self.enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sched_frame, text="Enable scheduled lock", variable=self.enabled_var,
                        font=ctk.CTkFont(size=14), command=self._on_schedule_changed).pack(anchor="w", padx=15, pady=5)

        time_frame = ctk.CTkFrame(sched_frame, fg_color="transparent")
        time_frame.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(time_frame, text="Start:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.start_var = ctk.StringVar(value="22:00")
        start_entry = ctk.CTkEntry(time_frame, textvariable=self.start_var, width=80,
                                   font=ctk.CTkFont(size=14), justify="center")
        start_entry.pack(side="left", padx=(5, 20))
        start_entry.bind("<KeyRelease>", lambda e: self._on_schedule_changed())

        ctk.CTkLabel(time_frame, text="End:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.end_var = ctk.StringVar(value="07:00")
        end_entry = ctk.CTkEntry(time_frame, textvariable=self.end_var, width=80,
                                 font=ctk.CTkFont(size=14), justify="center")
        end_entry.pack(side="left", padx=5)
        end_entry.bind("<KeyRelease>", lambda e: self._on_schedule_changed())

        self.sched_info = ctk.CTkLabel(sched_frame, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.sched_info.pack(anchor="w", padx=15)

        ctk.CTkButton(sched_frame, text="Save Schedule", font=ctk.CTkFont(size=14),
                      command=self.on_save_schedule).pack(anchor="e", padx=15, pady=(5, 15))

        # API section
        api_frame = self._section(main, "REST API")

        self.api_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(api_frame, text="Enable API server", variable=self.api_enabled_var,
                        font=ctk.CTkFont(size=14)).pack(anchor="w", padx=15, pady=5)

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

        self.api_info = ctk.CTkLabel(api_frame, text="", font=ctk.CTkFont(size=12), text_color=MUTED)
        self.api_info.pack(anchor="w", padx=15)

        ctk.CTkButton(api_frame, text="Save API", font=ctk.CTkFont(size=14),
                      command=self.on_save_api).pack(anchor="e", padx=15, pady=(5, 15))

        # Security / startup section
        pw_frame = self._section(main, "Security")

        self.startup_var = ctk.BooleanVar(value=core.is_startup_installed())
        ctk.CTkCheckBox(pw_frame, text="Start with Windows", variable=self.startup_var,
                        font=ctk.CTkFont(size=14), command=self.on_toggle_startup).pack(anchor="w", padx=15, pady=5)

        ctk.CTkButton(pw_frame, text="Change Password", font=ctk.CTkFont(size=14), fg_color="gray40",
                      hover_color="gray30", command=self.on_change_password).pack(anchor="e", padx=15, pady=(5, 15))

        # Appearance toggle
        appear_frame = ctk.CTkFrame(main, fg_color="transparent")
        appear_frame.pack(fill="x")

        ctk.CTkLabel(appear_frame, text="Theme:", font=ctk.CTkFont(size=12)).pack(side="left")

        self.appearance_menu = ctk.CTkOptionMenu(appear_frame, values=["Dark", "Light", "System"],
                                                 command=self._change_appearance, width=100,
                                                 font=ctk.CTkFont(size=12))
        self.appearance_menu.pack(side="left", padx=10)
        self.appearance_menu.set("Dark")

    def _change_appearance(self, mode: str):
        ctk.set_appearance_mode(mode.lower())

    def _on_schedule_changed(self):
        if not self._loading:
            self._schedule_dirty = True

    # --- state -> widgets -----------------------------------------------------------
    def update_status(self):
        st = self.locker.state
        if st.active:
            text = "Locked (schedule)" if st.reason == 'schedule' else "Locked"
            self.status_label.configure(text=text)
            self.status_indicator.configure(text_color=RED)
            self.lock_btn.configure(state="disabled")
        else:
            self.status_label.configure(text="Unlocked")
            self.status_indicator.configure(text_color=GREEN)
            self.lock_btn.configure(state="normal")

    def _schedule_info_text(self, sched: dict) -> str:
        if not sched.get('enabled'):
            return "Schedule is off"
        if is_snoozed(datetime.now(), sched):
            until = datetime.fromisoformat(sched['snooze_until']).strftime('%H:%M')
            return f"Unlocked for tonight - schedule resumes after {until}"
        return f"Locks daily {sched['start']}-{sched['end']}"

    def load_into_ui(self):
        try:
            self._loading = True
            sched = read_schedule()
            self.enabled_var.set(bool(sched.get('enabled', False)))
            self.start_var.set(sched.get('start', '22:00'))
            self.end_var.set(sched.get('end', '07:00'))
            self.sched_info.configure(text=self._schedule_info_text(sched))

            api = load_config().get('api', {})
            self.api_enabled_var.set(bool(api.get('enabled', False)))
            self.api_host_var.set(str(api.get('host', '127.0.0.1')))
            self.api_port_var.set(str(api.get('port', 8765)))
        except Exception as e:
            print(f'[ui] load failed: {e}')
        finally:
            self._loading = False
            self._schedule_dirty = False

    def tick(self):
        self.update_status()
        try:
            sched = read_schedule()
            self.sched_info.configure(text=self._schedule_info_text(sched))
            # Reflect changes made elsewhere (API) unless the user is editing the form
            if not self._schedule_dirty:
                self._loading = True
                if self.enabled_var.get() != sched['enabled']:
                    self.enabled_var.set(sched['enabled'])
                if self.start_var.get() != sched['start']:
                    self.start_var.set(sched['start'])
                if self.end_var.get() != sched['end']:
                    self.end_var.set(sched['end'])
        except Exception:
            pass
        finally:
            self._loading = False
        self.root.after(1000, self.tick)

    # --- actions --------------------------------------------------------------------
    def _confirm_password(self, prompt: str) -> bool:
        pw = ask_password(self.root, 'Confirm', prompt)
        if pw is None:
            return False
        if not verify_password(pw):
            messagebox.showerror('Error', 'Incorrect password.')
            return False
        return True

    def on_lock_now(self):
        try:
            self.locker.lock_now(reason='manual')
            self.update_status()
        except Exception as e:
            messagebox.showerror('Error', f'Failed to lock: {e}')

    def on_save_schedule(self):
        try:
            start = fmt_hhmm(parse_hhmm(self.start_var.get()))
            end = fmt_hhmm(parse_hhmm(self.end_var.get()))
            if start == end:
                raise ValueError('start and end must differ')
        except ValueError as e:
            messagebox.showerror('Error', f'Invalid schedule: {e}')
            return
        if not self._confirm_password('Enter password to save schedule:'):
            return
        try:
            sched = update_schedule(enabled=bool(self.enabled_var.get()), start=start, end=end, snooze_until=None)
            self._schedule_dirty = False
            self.load_into_ui()
            messagebox.showinfo('Saved', self._schedule_info_text(sched))
        except Exception as e:
            messagebox.showerror('Error', f'Failed to save schedule: {e}')

    def _start_api(self, show_errors: bool):
        try:
            self.api_server = maybe_start_api(self.locker)
        except OSError as e:
            self.api_server = None
            self.api_info.configure(text=f"Could not start: {e.strerror or e}", text_color=RED)
            if show_errors:
                messagebox.showerror('API', f'Could not start the API server: {e}')
            return
        if self.api_server:
            self.api_info.configure(text=f"Running on http://{self.api_server.host}:{self.api_server.port}",
                                    text_color=MUTED)
        else:
            self.api_info.configure(text="Stopped", text_color=MUTED)

    def on_save_api(self):
        try:
            enabled = bool(self.api_enabled_var.get())
            host = self.api_host_var.get().strip() or '127.0.0.1'
            port = int(self.api_port_var.get().strip() or '8765')
            if not 1 <= port <= 65535:
                raise ValueError('port must be between 1 and 65535')
        except ValueError as e:
            messagebox.showerror('Error', f'Invalid API settings: {e}')
            return
        if not self._confirm_password('Enter password to save API settings:'):
            return
        update_api(enabled, host, port)
        if self.api_server:
            try:
                self.api_server.stop()
            except Exception:
                pass
            self.api_server = None
        self._start_api(show_errors=True)
        if self.api_server or not enabled:
            messagebox.showinfo('Saved', 'API settings updated.')

    def on_toggle_startup(self):
        want = bool(self.startup_var.get())
        try:
            core.install_startup() if want else core.uninstall_startup()
        except Exception as e:
            messagebox.showerror('Error', f'Failed to update startup setting: {e}')
        self.startup_var.set(core.is_startup_installed())

    def on_change_password(self):
        old_pw = ask_password(self.root, 'Change Password', 'Enter current password:')
        if old_pw is None:
            return
        if not verify_password(old_pw):
            messagebox.showerror('Error', 'Current password is incorrect.')
            return
        new_pw = self._ask_new_password('Change Password')
        if new_pw is None:
            return
        try:
            set_password(new_pw)
            messagebox.showinfo('Success', 'Password changed.')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to change password: {e}')

    def _ask_new_password(self, title: str) -> str | None:
        while True:
            new_pw = ask_password(self.root, title, 'Enter new password:')
            if new_pw is None:
                return None
            if len(new_pw) < 4:
                messagebox.showerror('Error', 'Password must be at least 4 characters.')
                continue
            if ask_password(self.root, title, 'Confirm new password:') != new_pw:
                messagebox.showerror('Error', 'Passwords do not match.')
                continue
            return new_pw

    def ensure_password_set(self) -> bool:
        """First run: require a password. Returns False if the user cancels (app exits)."""
        if has_password():
            return True
        new_pw = self._ask_new_password('Set Password')
        if new_pw is None:
            messagebox.showerror('Required', 'A password is required. PC Lock will exit.')
            return False
        set_password(new_pw)
        messagebox.showinfo('Success', 'Password set.')
        return True

    def request_exit(self):
        self.show_window()
        if not self._confirm_password('Enter password to exit:'):
            return
        self.scheduler.stop()
        self.tray.stop()
        if self.api_server:
            try:
                self.api_server.stop()
            except Exception:
                pass
        self.root.destroy()

    def minimize_to_tray(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()


def main():
    root = ctk.CTk()
    AppUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
