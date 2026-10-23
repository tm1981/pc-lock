"""
Schedule evaluation and the background scheduler thread (shared by console and GUI modes).
"""
import math
import threading
from datetime import datetime, time as dtime, timedelta

from schedule_store import read_schedule, update_schedule, DEFAULT_NOTIFY_MINUTES


def parse_hhmm(value: str) -> dtime:
    """Parse 'H:MM' or 'HH:MM' (24h). Raises ValueError on bad input."""
    parts = str(value).strip().split(':')
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit() or len(parts[1]) != 2:
        raise ValueError(f'time must be HH:MM, got {value!r}')
    return dtime(int(parts[0]), int(parts[1]))


def fmt_hhmm(t: dtime) -> str:
    return t.strftime('%H:%M')


def in_lock_window(now: datetime, start: dtime, end: dtime) -> bool:
    cur = now.time()
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    # overnight
    return cur >= start or cur < end


def window_end(now: datetime, start: dtime, end: dtime) -> datetime | None:
    """End of the lock window containing `now`, or None when outside a window."""
    if not in_lock_window(now, start, end):
        return None
    end_dt = datetime.combine(now.date(), end)
    if end_dt <= now:
        end_dt += timedelta(days=1)
    return end_dt


def next_window_start(now: datetime, start: dtime) -> datetime:
    start_dt = datetime.combine(now.date(), start)
    if start_dt <= now:
        start_dt += timedelta(days=1)
    return start_dt


def is_snoozed(now: datetime, sched: dict) -> bool:
    snooze = sched.get('snooze_until')
    if not snooze:
        return False
    try:
        return now < datetime.fromisoformat(snooze)
    except ValueError:
        return False


def should_lock(now: datetime, sched: dict) -> bool:
    if not sched.get('enabled'):
        return False
    try:
        start, end = parse_hhmm(sched['start']), parse_hhmm(sched['end'])
    except (KeyError, ValueError):
        return False
    return in_lock_window(now, start, end) and not is_snoozed(now, sched)


def snooze_current_window(now: datetime | None = None) -> None:
    """Skip the rest of the current scheduled window (schedule stays enabled for the next one)."""
    now = now or datetime.now()
    sched = read_schedule()
    try:
        start, end = parse_hhmm(sched['start']), parse_hhmm(sched['end'])
    except ValueError:
        return
    end_dt = window_end(now, start, end)
    if end_dt is not None:
        update_schedule(snooze_until=end_dt.isoformat(timespec='seconds'))


class SchedulerThread(threading.Thread):
    """Checks the schedule every second: locks/unlocks and shows warning toasts before a lock."""

    def __init__(self, locker, notify: bool = True):
        super().__init__(daemon=True, name='pclock-scheduler')
        self.locker = locker
        self.notify = notify
        self._stop_event = threading.Event()
        self._notified: set[int] = set()
        self._notified_for: datetime | None = None  # the window start the warnings belong to

    def stop(self):
        self._stop_event.set()

    def tick(self, now: datetime | None = None):
        now = now or datetime.now()
        sched = read_schedule()
        if should_lock(now, sched):
            if not self.locker.state.active:
                self.locker.lock_now(reason='schedule', start=sched['start'], end=sched['end'])
            return
        # Outside the window (or snoozed): end a schedule lock, never a manual one
        if self.locker.state.active and self.locker.state.reason == 'schedule':
            self.locker.unlock_now(snooze=False)
        if sched.get('enabled') and not self.locker.state.active:
            self._maybe_warn(now, sched)

    def _maybe_warn(self, now: datetime, sched: dict):
        try:
            start = parse_hhmm(sched['start'])
        except ValueError:
            return
        start_dt = next_window_start(now, start)
        if self._notified_for != start_dt:
            self._notified_for = start_dt
            self._notified.clear()
        # A snoozed window still "starts" now; don't warn for it
        if is_snoozed(start_dt, sched):
            return
        remaining = (start_dt - now).total_seconds()
        thresholds = sorted(sched.get('notify_minutes') or DEFAULT_NOTIFY_MINUTES, reverse=True)
        due = [m for m in thresholds if remaining <= m * 60 and m not in self._notified]
        if not due:
            return
        # Several thresholds may be due at once (e.g. app started 2 min before lock): one toast
        self._notified.update(due)
        if self.notify:
            from notifications import show_lock_warning
            show_lock_warning(max(1, math.ceil(remaining / 60)))

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f'[scheduler] {e}')
            self._stop_event.wait(1)
