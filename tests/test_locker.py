import threading
import time

import main
from main import Locker
from schedule_store import read_schedule, write_schedule


class FakeProc:
    def __init__(self):
        self._done = threading.Event()
        self.code = None

    def exit(self, code):
        self.code = code
        self._done.set()

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self.code

    def poll(self):
        return self.code

    def terminate(self):
        self.exit(1)


def make_locker(monkeypatch):
    procs = []
    switches = []
    monkeypatch.setattr(main, '_switch_to_default_desktop', lambda: switches.append(1))
    locker = Locker()
    monkeypatch.setattr(locker, '_mute_system', lambda: None)
    monkeypatch.setattr(locker, '_restore_audio', lambda: None)

    def spawn(reason, start, end):
        p = FakeProc()
        procs.append(p)
        return p
    monkeypatch.setattr(locker, '_spawn', spawn)
    return locker, procs, switches


def wait_until(cond, timeout=2):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_unlock_does_not_disable_schedule(monkeypatch):
    # Old bug: the watcher raced unlock_now and disabled the schedule every morning
    write_schedule(True, '00:00', '23:59')
    locker, procs, _ = make_locker(monkeypatch)
    locker.lock_now('schedule', '00:00', '23:59')
    locker.unlock_now(snooze=False)
    time.sleep(0.1)
    assert read_schedule()['enabled'] is True
    assert not locker.state.active


def test_password_unlock_snoozes_and_returns_to_default_desktop(monkeypatch):
    write_schedule(True, '00:00', '23:59')
    locker, procs, switches = make_locker(monkeypatch)
    locker.lock_now('schedule', '00:00', '23:59')
    procs[0].exit(0)  # lock screen: correct password
    assert wait_until(lambda: not locker.state.active)
    assert wait_until(lambda: read_schedule()['snooze_until'] is not None)
    assert read_schedule()['enabled'] is True
    assert switches


def test_crashed_lockscreen_is_restarted(monkeypatch):
    locker, procs, switches = make_locker(monkeypatch)
    locker.lock_now('manual')
    procs[0].exit(3)  # crash / Alt+F4: must not count as unlock
    assert wait_until(lambda: len(procs) == 2)
    assert locker.state.active and locker.state.process is procs[1]
    # Fail closed: repeated crashes keep it locked, never switch back to the normal desktop
    for i in range(1, 4):
        assert wait_until(lambda: len(procs) > i, timeout=10)
        procs[i].exit(3)
    assert wait_until(lambda: len(procs) == 5, timeout=10)
    assert locker.state.active and not switches
    # Correct password on the restarted lock screen ends it normally
    procs[4].exit(0)
    assert wait_until(lambda: not locker.state.active)
    assert switches
