"""
Windows Toast Notifications for PC-Lock

Provides warning notifications before scheduled locks.
Uses winotify for pure Python Windows 10/11 toast support.
"""
import os
import sys
import threading
from pathlib import Path


def _get_icon_path() -> str | None:
    """Get the app icon path for notifications."""
    try:
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            candidate = os.path.join(base, 'assets', 'pclock.ico')
            if os.path.exists(candidate):
                return candidate
        else:
            candidate = Path(__file__).with_name('assets') / 'pclock.ico'
            if candidate.exists():
                return str(candidate)
    except Exception:
        pass
    return None


def show_lock_warning(minutes: int) -> None:
    """
    Show a toast notification warning that lock is imminent.

    Args:
        minutes: Minutes until lock (e.g., 5 or 1)
    """
    def _show():
        try:
            from winotify import Notification, audio

            if minutes == 1:
                title = "⚠️ Locking in 1 minute"
                body = "Your desktop will be locked in 1 minute."
            else:
                title = f"🔒 Locking in {minutes} minutes"
                body = f"Your desktop will be locked in {minutes} minutes."

            toast = Notification(
                app_id="PC Lock",
                title=title,
                msg=body,
                duration="short"
            )

            icon = _get_icon_path()
            if icon:
                toast.set_audio(audio.Default, loop=False)
                toast.icon = icon

            toast.show()
        except Exception as e:
            # Silently fail - notifications are non-critical
            print(f"[notifications] Warning toast failed: {e}")

    # Run in thread to avoid blocking
    threading.Thread(target=_show, daemon=True).start()


def show_locked_notification() -> None:
    """Show notification that desktop is now locked."""
    def _show():
        try:
            from winotify import Notification

            toast = Notification(
                app_id="PC Lock",
                title="🔐 Desktop Locked",
                msg="Press Ctrl+Alt+U to unlock.",
                duration="short"
            )

            icon = _get_icon_path()
            if icon:
                toast.icon = icon

            toast.show()
        except Exception:
            pass

    threading.Thread(target=_show, daemon=True).start()


def show_unlocked_notification() -> None:
    """Show notification that desktop is now unlocked."""
    def _show():
        try:
            from winotify import Notification

            toast = Notification(
                app_id="PC Lock",
                title="🔓 Desktop Unlocked",
                msg="Welcome back!",
                duration="short"
            )

            icon = _get_icon_path()
            if icon:
                toast.icon = icon

            toast.show()
        except Exception:
            pass

    threading.Thread(target=_show, daemon=True).start()


# Notification warning intervals (minutes before lock)
DEFAULT_NOTIFY_MINUTES = [5, 1]
