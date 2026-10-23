from datetime import datetime, time as dtime

import pytest

import notifications
from scheduler import (SchedulerThread, in_lock_window, parse_hhmm, should_lock, snooze_current_window,
                       window_end)
from schedule_store import read_schedule, update_schedule, write_schedule


def dt(h, m, day=10, s=0):
    return datetime(2026, 10, day, h, m, s)


class FakeState:
    def __init__(self):
        self.active = False
        self.reason = None


class FakeLocker:
    def __init__(self):
        self.state = FakeState()
        self.calls = []

    def lock_now(self, reason='manual', start=None, end=None):
        self.calls.append(('lock', reason))
        self.state.active, self.state.reason = True, reason

    def unlock_now(self, snooze=True):
        self.calls.append(('unlock', snooze))
        self.state = FakeState()


def test_parse_hhmm():
    assert parse_hhmm('7:05') == dtime(7, 5)
    assert parse_hhmm(' 22:00 ') == dtime(22, 0)
    for bad in ('25:00', '7', '7:5', 'ab:cd', '', '12:60'):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_overnight_window():
    s, e = dtime(22), dtime(7)
    assert in_lock_window(dt(23, 0), s, e)
    assert in_lock_window(dt(3, 0), s, e)
    assert not in_lock_window(dt(7, 0), s, e)
    assert not in_lock_window(dt(12, 0), s, e)
    assert window_end(dt(23, 0), s, e) == dt(7, 0, day=11)
    assert window_end(dt(3, 0), s, e) == dt(7, 0)
    assert window_end(dt(12, 0), s, e) is None


def test_snooze_skips_only_current_window():
    write_schedule(True, '22:00', '07:00')
    snooze_current_window(dt(23, 0))
    sched = read_schedule()
    assert sched['enabled'] is True                  # schedule is NOT disabled any more
    assert sched['snooze_until'] == '2026-10-11T07:00:00'
    assert not should_lock(dt(23, 30), sched)        # rest of tonight skipped
    assert should_lock(dt(22, 30, day=11), sched)    # next night locks again


def test_update_schedule_keeps_other_fields():
    write_schedule(True, '22:00', '07:00', notify_minutes=[10, 2])
    update_schedule(start='21:00')
    s = read_schedule()
    assert (s['start'], s['end'], s['notify_minutes'], s['enabled']) == ('21:00', '07:00', [10, 2], True)


def test_tick_locks_and_ends_only_schedule_locks():
    write_schedule(True, '22:00', '07:00')
    locker = FakeLocker()
    t = SchedulerThread(locker, notify=False)
    t.tick(dt(23, 0))
    assert locker.calls == [('lock', 'schedule')]
    t.tick(dt(7, 1))
    assert locker.calls[-1] == ('unlock', False)

    # A manual lock must survive the end of the window
    locker = FakeLocker()
    locker.lock_now('manual')
    SchedulerThread(locker, notify=False).tick(dt(7, 1))
    assert locker.state.active and locker.state.reason == 'manual'


def test_warnings_fire_once_per_threshold(monkeypatch):
    shown = []
    monkeypatch.setattr(notifications, 'show_lock_warning', lambda m: shown.append(m))
    write_schedule(True, '22:00', '07:00', notify_minutes=[5, 1])
    t = SchedulerThread(FakeLocker(), notify=True)
    t.tick(dt(21, 50))
    t.tick(dt(21, 55, s=30))
    t.tick(dt(21, 55, s=31))
    t.tick(dt(21, 59, s=10))
    assert shown == [5, 1]


def test_warning_at_startup_reports_real_minutes(monkeypatch):
    shown = []
    monkeypatch.setattr(notifications, 'show_lock_warning', lambda m: shown.append(m))
    write_schedule(True, '22:00', '07:00', notify_minutes=[5, 1])
    t = SchedulerThread(FakeLocker(), notify=True)
    t.tick(dt(21, 58))        # 2 minutes left: one toast saying 2, not "5"
    t.tick(dt(21, 59, s=30))  # 1-minute threshold now due
    assert shown == [2, 1]
