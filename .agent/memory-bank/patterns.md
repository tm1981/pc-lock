# Patterns & Flows

## Lock Flow

```
Locker.lock_now(reason, start, end)          (thread-safe: RLock)
    |- Mute audio via pycaw (COM initialised per call; old + new pycaw API)
    |- Open LockDesktop once, handle kept for app lifetime
    |- Spawn lockscreen child ([frozen] pclock.exe --mode lockscreen | [dev] python lockscreen.py)
    |- LockState(active=True, reason, since)
    `- Watcher thread waits for child exit
```

## Unlock Paths

```
A) Password on lock screen (Ctrl+Alt+U -> inline entry -> Enter)
     lockscreen switches to Default, os._exit(0)
     watcher sees exit code 0 -> switch Default, restore audio, clear state,
     if reason == 'schedule': snooze_current_window()  (schedule stays ENABLED)

B) unlock_now()  (API / scheduler at window end / Ctrl+C)
     clears state FIRST (watcher then ignores the exit), switch Default,
     terminate child, restore audio, snooze if reason == 'schedule' and snooze=True

C) Lock screen crashes / Alt+F4 / mainloop ends -> exit code != 0
     watcher respawns lock screen (max 3 per lock), then gives up and
     switches back to Default so the user is never stuck on an empty desktop
```

## Schedule Check (scheduler.SchedulerThread, 1s, used by GUI AND console)

```
tick(now)
    |- read_schedule()  (DPAPI)
    |- should_lock = enabled AND in_lock_window AND not snoozed
    |- should_lock and not active -> lock_now('schedule')
    |- not should_lock and active and reason == 'schedule' -> unlock_now(snooze=False)
    |     (manual locks are never ended by the schedule)
    `- outside window -> warning toasts once per threshold, text shows real minutes left
```

`snooze_until` (ISO datetime in schedule.dat) = end of the window the user unlocked.
It expires by itself; any schedule save (UI or API) clears it.

## Threading Rule (UI)

Tk is only touched on the Tk thread. Tray callbacks and other threads call
`AppUI.post(fn)`; a 100ms `_drain_actions` loop runs them. The same loop polls the
single-instance "show window" event (`single_instance.py`).

## Configuration Flow

```
First Run:
    load_config() → no file exists → create default config.json
    │
    └─► UI prompts for initial password via set_password()

Password Setting:
    set_password(new_password)
        ├─► Generate 16-byte random salt
        ├─► PBKDF2-HMAC-SHA256 with 200k iterations
        └─► Save salt + hash to config.json

Password Verification:
    verify_password(password)
        ├─► Load salt from config
        ├─► Compute PBKDF2 hash
        └─► Compare to stored hash
```

## API Authentication

```
Request arrives at /api/lock, /api/unlock, /api/schedule
    │
    ├─► Check Authorization: Bearer <password>
    │   └─► verify_password(token)
    │
    ├─► OR check JSON body {"password": "..."}
    │   └─► verify_password(body.password)
    │
    └─► Return 401 if neither valid
```

## Single Instance Pattern

```
_ensure_single_instance()
    │
    ├─► CreateMutexW('Global\\PC_LOCK_SINGLETON')
    │
    ├─► If ERROR_ALREADY_EXISTS:
    │   ├─► FindWindowW('PC Lock')
    │   ├─► ShowWindow + SetForegroundWindow
    │   └─► sys.exit(0)
    │
    └─► Keep mutex handle alive
```
