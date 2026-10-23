# Components Reference

## main.py
**Entry point, Locker, startup registry, single-instance guard**

| Item | Description |
|------|-------------|
| `Locker` | Thread-safe lock state, child spawn/respawn, audio mute/restore, `status()` |
| `LockState` | Dataclass: process, active, reason, start, end, since |
| `install_startup()` / `uninstall_startup()` / `is_startup_installed()` | HKCU Run (frozen exe, or pythonw + `--ui`) |
| `_ensure_single_instance()` | Global mutex; a second launch signals `single_instance` and exits |

## scheduler.py
**Pure schedule logic + `SchedulerThread` (shared by GUI and console)**

`parse_hhmm`, `fmt_hhmm`, `in_lock_window`, `window_end`, `next_window_start`,
`is_snoozed`, `should_lock`, `snooze_current_window`, `SchedulerThread.tick(now)`.
`ui/scheduler.py` only re-exports it.

## single_instance.py
Named auto-reset event `Local\PC_LOCK_SHOW_WINDOW`: `signal_show()`, `show_requested()`.

---

## ui/ (Package)
**Modern CustomTkinter GUI with system tray**

### Module Structure
| Module | Lines | Description |
|--------|-------|-------------|
| `ui/__init__.py` | ~12 | Package exports for backward compatibility |
| `ui/app.py` | ~430 | Main AppUI class, window setup, event handlers |
| `ui/dialogs.py` | ~52 | PasswordDialog class and ask_password helper |
| `ui/scheduler.py` | ~8 | Re-export of top-level scheduler |
| `ui/tray.py` | ~80 | TrayManager for pystray system tray |

### Key Classes
| Class | Module | Description |
|-------|--------|-------------|
| `AppUI` | app.py | Main window (420x680), dark theme, all config panels |
| `SchedulerThread` | ../scheduler.py | Re-exported shared scheduler |
| `TrayManager` | tray.py | pystray integration for system tray |
| `PasswordDialog` | dialogs.py | Modern CTkToplevel password input |

### UI Sections
- **Status frame**: Colored indicator (🟢/🔴), Lock Now button
- **Schedule frame**: Enable checkbox, start/end time entries, Save button
- **API frame**: Enable checkbox, host/port inputs, Save button
- **Security frame**: Start with Windows checkbox, Change password button
- **Theme selector**: Dark/Light/System dropdown

### Features
- **Dark theme by default** with system theme support
- **Rounded widgets** via CustomTkinter
- **Notification integration** - shows warnings before lock
- **Tray** - icon always visible; password-protected exit
- **Status lines** - schedule state (off / daily / skipped tonight) and API running/error

---

## notifications.py (110 lines)
**Windows toast notifications via winotify**

| Function | Description |
|----------|-------------|
| `show_lock_warning(minutes)` | Toast warning N minutes before lock |
| `show_locked_notification()` | Notification when locked |
| `show_unlocked_notification()` | Welcome back notification |
| `_get_icon_path()` | Finds app icon for toast |

**Default intervals**: `[5, 1]` (5 min and 1 min before lock)

---

## lockscreen.py
**Lock screen on the alternate desktop**

- Per-monitor fullscreen windows (DPI aware), clock + message
- Hotkey from config (`hotkey_to_tk`), default Ctrl+Alt+U, shows an inline password entry
- 5 wrong attempts -> input disabled 30s x n; panel hides after 30s idle
- Alt+F4 / close ignored; exit code 0 only on correct password, otherwise 3
- Fails closed: with no readable password hash nothing unlocks (Ctrl+Alt+Del -> sign out is the escape)

---

## desktop.py (113 lines)
**Win32 Desktop API wrapper**

| Function | Win32 API | Description |
|----------|-----------|-------------|
| `create_or_open_desktop(name)` | CreateDesktopW/OpenDesktopW | Create or get handle |
| `open_desktop(name)` | OpenDesktopW | Open existing |
| `switch_desktop(hdesk)` | SwitchDesktop | Change visible desktop |
| `set_thread_desktop(hdesk)` | SetThreadDesktop | Bind thread |
| `close_desktop(hdesk)` | CloseDesktop | Release handle |

**Constants**: `DEFAULT_DESKTOP = 'Default'`, `LOCK_DESKTOP = 'LockDesktop'`

---

## config.py (101 lines)
**Configuration management**

| Function | Description |
|----------|-------------|
| `get_app_dir()` | Returns `%LOCALAPPDATA%/PC-Lock/` |
| `get_config_path()` | Returns config.json path |
| `load_config()` / `save_config(cfg)` | JSON persistence |
| `verify_password(password)` | PBKDF2 hash comparison |
| `set_password(new_password)` | Generate salt, compute hash |
| `update_api(enabled, host, port)` | Update API settings |

---

## schedule_store.py
**DPAPI-encrypted schedule storage** (`%LOCALAPPDATA%/PC-Lock/schedule.dat`, atomic writes)

| Function | Description |
|----------|-------------|
| `read_schedule()` | Decrypt; corrupt -> defaults (disabled) |
| `write_schedule(enabled, start, end, notify_minutes, snooze_until)` | Encrypt and save |
| `update_schedule(**changes)` | Read-modify-write, keeps other fields |

```json
{"enabled": true, "start": "22:00", "end": "07:00", "notify_minutes": [5, 1], "snooze_until": null}
```

---

## api.py
**REST API** (ThreadingHTTPServer; CORS headers on every response; per-IP auth throttle 5 fails/60s -> 429)

| Endpoint | Method | Auth | Response |
|----------|--------|------|----------|
| `/api/status` | GET | No | `{locked, reason, since, schedule}` |
| `/api/schedule` | GET | No | `{schedule}` |
| `/api/lock` | POST | Yes | `{status: "locked", ...}` |
| `/api/unlock` | POST | Yes | `{status: "unlocked", ...}` (snoozes the scheduled window) |
| `/api/schedule` | POST | Yes | partial update; clears snooze |

`ApiServer.stop()` also calls `server_close()` so the port can be re-bound.
`maybe_start_api()` raises `OSError` if the port is taken (callers show/print it).

## config.py
`PCLOCK_APP_DIR` env var overrides the data folder (tests use it). Atomic writes,
`hmac.compare_digest`, `has_password()`.
