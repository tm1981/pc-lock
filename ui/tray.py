"""
System tray manager for PC-Lock UI.
"""
import os
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw
import pystray


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

    def stop(self):
        try:
            self.icon.visible = False
            self.icon.stop()
        except Exception:
            pass

    # Menu callbacks run on the pystray thread: never touch Tk here, hand off to the UI thread
    def on_open(self, icon, item):
        self.app.post(self.app.show_window)

    def on_lock(self, icon, item):
        self.app.post(self.app.on_lock_now)

    def on_exit(self, icon, item):
        self.app.post(self.app.request_exit)
