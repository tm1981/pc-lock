"""
Background scheduler thread for PC-Lock UI.
"""
import threading
import time
from datetime import datetime, time as dtime

import main as core
from notifications import show_lock_warning, DEFAULT_NOTIFY_MINUTES


def in_lock_window(now: datetime, start: dtime, end: dtime) -> bool:
    return core.in_lock_window(now, start, end)


class SchedulerThread(threading.Thread):
    """Background scheduler thread with notification support."""

    def __init__(self, locker: core.Locker, on_state_change=None):
        super().__init__(daemon=True)
        self.locker = locker
        self.on_state_change = on_state_change
        self._stop = threading.Event()
        self._notified_minutes = set()  # Track which warnings we've shown

    def stop(self):
        self._stop.set()

    def _minutes_until_lock(self, start: dtime) -> int | None:
        """Calculate minutes until lock window starts. Returns None if already in window."""
        now = datetime.now()
        cur = now.time()

        # If we're already in lock window, return None
        from schedule_store import read_schedule
        sched = read_schedule()
        try:
            end = dtime.fromisoformat(sched.get('end', '07:00'))
            if in_lock_window(now, start, end):
                return None
        except Exception:
            return None

        # Calculate time until start
        start_dt = datetime.combine(now.date(), start)
        if start_dt <= now:
            # Start is tomorrow
            from datetime import timedelta
            start_dt = start_dt + timedelta(days=1)

        diff = start_dt - now
        return int(diff.total_seconds() / 60)

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
                        notify_mins = sched.get('notify_minutes', DEFAULT_NOTIFY_MINUTES)

                        should_lock = in_lock_window(datetime.now(), start, end)

                        if should_lock and not self.locker.state.active:
                            # Reset notification tracking when we lock
                            self._notified_minutes.clear()
                            self.locker.lock_now(
                                reason='schedule',
                                start=start.isoformat(timespec='minutes'),
                                end=end.isoformat(timespec='minutes')
                            )
                            if self.on_state_change:
                                self.on_state_change(True)

                        elif not should_lock and self.locker.state.active:
                            self.locker.unlock_now()
                            self._notified_minutes.clear()
                            if self.on_state_change:
                                self.on_state_change(False)

                        elif not should_lock and not self.locker.state.active:
                            # Check for notification timing
                            mins = self._minutes_until_lock(start)
                            if mins is not None:
                                for notify_at in notify_mins:
                                    if mins <= notify_at and notify_at not in self._notified_minutes:
                                        show_lock_warning(notify_at)
                                        self._notified_minutes.add(notify_at)
                    except Exception:
                        pass
                else:
                    # Schedule disabled - clear notification tracking
                    self._notified_minutes.clear()
            except Exception:
                pass

            time.sleep(1)
