"""
System tray manager for PC-Lock UI.
"""
import os
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

from .dialogs import ask_password
from config import verify_password
from tkinter import messagebox


class TrayManager:
    """System tray icon manager."""

    def __init__(self, app: 'AppUI'):
        self.app = app
        self.icon = pystray.Icon('pc-lock', self._build_icon(), 'PC Lock', menu=pystray.Menu(
            pystray.MenuItem('Open', self.on_open),
            pystray.MenuItem('Lock now', self.on_lock),
            pystray.MenuItem('Exit', self.on_exit)
        ))
        self.thread = threading.Thread(target=self.icon.run, daemon=True)

    def _build_icon(self):
        # Try load packaged icon
        try:
            ico_path = None
            if getattr(sys, 'frozen', False):
                base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
                candidate = os.path.join(base, 'assets', 'pclock.ico')
                if os.path.exists(candidate):
                    ico_path = candidate
            else:
                candidate = Path(__file__).parent.parent / 'assets' / 'pclock.ico'
                if candidate.exists():
                    ico_path = str(candidate)
            if ico_path:
                return Image.open(ico_path)
        except Exception:
            pass

        # Fallback: draw simple lock icon
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([16, 28, 48, 50], fill=(0, 0, 0, 255))
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
        def prompt_and_exit():
            pw = ask_password(self.app.root, 'Exit PC Lock', 'Enter password to exit:')
            if pw and verify_password(pw):
                try:
                    self.app.scheduler.stop()
                except Exception:
                    pass
                self.icon.visible = False
                self.icon.stop()
                self.app.root.destroy()
            elif pw is not None:
                messagebox.showerror('Error', 'Incorrect password.')
        self.app.root.after(0, prompt_and_exit)
