# Patterns & Flows

## Lock Flow

```
Locker.lock_now(reason, start, end)
    │
    ├─► Mute audio via pycaw
    │
    ├─► Create/open alternate desktop
    │   └─► desktop.create_or_open_desktop('LockDesktop')
    │
    ├─► Spawn subprocess
    │   ├─► [frozen] pclock.exe --mode lockscreen --desktop-name LockDesktop
    │   └─► [dev] python lockscreen.py --desktop-name LockDesktop
    │
    ├─► Update LockState(active=True)
    │
    └─► Start watcher thread
        └─► Monitors process exit, resets state
```

## Unlock Flow

```
User presses Ctrl+Alt+U on lock screen
    │
    ├─► simpledialog password prompt
    │
    ├─► config.verify_password() validates
    │
    ├─► desktop.switch_desktop(Default)
    │
    ├─► Destroy all windows
    │
    └─► os._exit(0)
        │
        └─► Parent watcher thread detects exit
            ├─► If reason was 'schedule': disable schedule
            └─► Reset LockState()
```

## Schedule Check (1s interval)

```
scheduler_loop() or SchedulerThread.run()
    │
    ├─► schedule_store.read_schedule()
    │   └─► DPAPI decrypt schedule.dat
    │
    ├─► Parse start/end times (HH:MM)
    │
    ├─► in_lock_window(now, start, end)
    │   ├─► If start < end: direct range check
    │   └─► If start > end: overnight (spans midnight)
    │
    ├─► If should_lock AND not active:
    │   └─► locker.lock_now(reason='schedule')
    │
    └─► If not should_lock AND active:
        └─► locker.unlock_now()
```

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
