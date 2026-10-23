"""
Backward-compatible re-export: the scheduler now lives in the top-level `scheduler` module
so the console mode and the GUI share one implementation.
"""
from scheduler import SchedulerThread, in_lock_window

__all__ = ['SchedulerThread', 'in_lock_window']
