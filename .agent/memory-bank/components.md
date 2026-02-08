# Components Reference

## main.py (379 lines)
**Entry point and core orchestrator**

### Classes
| Class | Description |
|-------|-------------|
| `Locker` | Lock state management, process spawning, audio control |
| `LockState` | Dataclass: process, active, reason, start, end |

### Key Functions
| Function | Description |
|----------|-------------|
| `scheduler_loop(locker)` | Infinite loop checking schedule every 1s |
| `lock_if_in_schedule_now(locker)` | Immediate schedule check on startup |
| `in_lock_window(now, start, end)` | Time comparison with overnight support |
| `_ensure_single_instance()` | Global mutex singleton enforcement |
| `install_startup()` / `uninstall_startup()` | HKCU Run registry ops |
| `set_password_interactive()` | CLI password setup |

---

## ui/ (Package)
**Modern CustomTkinter GUI with system tray**

### Module Structure
| Module | Lines | Description |
|--------|-------|-------------|
| `ui/__init__.py` | ~12 | Package exports for backward compatibility |
| `ui/app.py` | ~430 | Main AppUI class, window setup, event handlers |
| `ui/dialogs.py` | ~52 | PasswordDialog class and ask_password helper |
| `ui/scheduler.py` | ~98 | SchedulerThread with notification timing |
| `ui/tray.py` | ~80 | TrayManager for pystray system tray |

### Key Classes
| Class | Module | Description |
|-------|--------|-------------|
| `AppUI` | app.py | Main window (420x680), dark theme, all config panels |
| `SchedulerThread` | scheduler.py | Background scheduler with notification support |
| `TrayManager` | tray.py | pystray integration for system tray |
| `PasswordDialog` | dialogs.py | Modern CTkToplevel password input |

### UI Sections
- **Status frame**: Colored indicator (🟢/🔴), Lock Now button
- **Schedule frame**: Enable checkbox, start/end time entries, Save button
- **API frame**: Enable checkbox, host/port inputs, Save button
- **Security frame**: Change password button
- **Theme selector**: Dark/Light/System dropdown

### Features
- **Dark theme by default** with system theme support
- **Rounded widgets** via CustomTkinter
- **Notification integration** - shows warnings before lock
- **Tray minimize** - password-protected exit

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

## lockscreen.py (164 lines)
**Lock screen display on alternate desktop**

### Classes
| Class | Description |
|-------|-------------|
| `LockScreen` | Fullscreen windows, hotkey binding, password prompt |

### Key Methods
| Method | Description |
|--------|-------------|
| `_build_window_for_monitor(m)` | Creates Tk/Toplevel per monitor |
| `_bind_hotkeys()` | Ctrl+Alt+U triggers unlock |
| `_on_hotkey()` | Password dialog, switches back on success |
| `run()` | Main loop with unlock polling |

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

## schedule_store.py (82 lines)
**DPAPI-encrypted schedule storage**

| Function | Description |
|----------|-------------|
| `read_schedule()` | Decrypt and return schedule dict |
| `write_schedule(enabled, start, end, notify_minutes)` | Encrypt and save |
| `_dpapi_protect(data)` | CryptProtectData wrapper |
| `_dpapi_unprotect(data)` | CryptUnprotectData wrapper |

**Schedule structure**:
```json
{
  "enabled": true,
  "start": "22:00",
  "end": "07:00",
  "notify_minutes": [5, 1]
}
```

**Storage**: `%LOCALAPPDATA%/PC-Lock/schedule.dat`

---

## api.py (139 lines)
**REST API server**

### Endpoints
| Endpoint | Method | Auth | Response |
|----------|--------|------|----------|
| `/api/status` | GET | No | `{"locked": bool}` |
| `/api/lock` | POST | Yes | `{"status": "locked"}` |
| `/api/unlock` | POST | Yes | `{"status": "unlocked"}` |
| `/api/schedule` | POST | Yes | `{"schedule": {...}}` |

### Classes
| Class | Description |
|-------|-------------|
| `ApiServer` | ThreadingHTTPServer wrapper |
| `_Handler` | Request handler with auth |
