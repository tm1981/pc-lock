"""
PC-Lock Modern UI Package

Re-exports main UI components for backward compatibility.
"""
from .app import AppUI, main
from .dialogs import PasswordDialog, ask_password
from .scheduler import SchedulerThread
from .tray import TrayManager

__all__ = ['AppUI', 'main', 'PasswordDialog', 'ask_password', 'SchedulerThread', 'TrayManager']
