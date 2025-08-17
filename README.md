# PC Lock (Windows)

A lightweight Windows app that locks the desktop by switching to an alternate desktop and showing a full-screen message on all monitors. Unlock requires a hotkey followed by a password.

Notes:
- Implemented in Python using Win32 APIs via `ctypes`.
- Uses an alternate desktop (WinSta0\\LockDesktop) to isolate input from other apps. CTRL+ALT+DEL is still available by design (cannot be blocked by user apps).
- Simple daily schedule supported.

## Features
- Lock/unlock via alternate desktop (robust vs. simple overlays).
- Full-screen, always-on-top lock screen across monitors.
- Configurable unlock hotkey (default: Ctrl+Alt+U).
- Password-protected unlock (PBKDF2-HMAC with per-install salt).
- Daily lock window scheduling.
- Optional REST API (localhost by default) to lock/unlock remotely with password auth.

## Install

1. Install Python 3.10+ on Windows.
2. Create a venv (recommended):

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. First run will generate a default `config.json` with a random password. Change it immediately:

```powershell
python main.py --set-password
```

Follow the prompt to set a new password.

## Usage

GUI (recommended):

```powershell
python ui.py
```

- Click "Lock now" to test
- Change schedule and click "Save schedule"
- Change password requires the current password
- Closing the window sends the app to the system tray. Use the tray icon to Open, Lock now, or Exit (password required).

Console scheduler:

```powershell
python main.py
```

- Lock immediately (for testing):

```powershell
python main.py --lock-now
```

- Unlock during lock screen: press `Ctrl+Alt+U`, enter your password, and press Enter.

- To exit the scheduler app, press Ctrl+C in the console.

## REST API
If enabled in `config.json` (`api.enabled: true`), a local REST server starts.

- Default base URL: http://127.0.0.1:8765
- Auth: provide the configured unlock password either as JSON `{ "password": "..." }` in the request body, or as `Authorization: Bearer <password>` header.

Endpoints:
- POST /api/lock
  - Body: `{ "password": "your_password" }`
  - Response: `{ "status": "locked" }`

- POST /api/unlock
  - Body: `{ "password": "your_password" }`
  - Response: `{ "status": "unlocked" }`

- GET /api/status
  - Response: `{ "locked": true | false }`

Examples (PowerShell):

```powershell
# Lock
curl -Method POST -Uri http://127.0.0.1:8765/api/lock -ContentType application/json -Body '{"password":"YOURPASS"}'

# Unlock
curl -Method POST -Uri http://127.0.0.1:8765/api/unlock -ContentType application/json -Body '{"password":"YOURPASS"}'

# Status
curl http://127.0.0.1:8765/api/status
```

Security notes:
- The API binds to localhost by default. Do not expose externally unless you understand the risks.
- Authentication uses your unlock password; protect it as you would your desktop password.

## Configure schedule

Edit `config.json`:

```json
{
  "hotkey": "ctrl+alt+u",
  "schedule": {
    "enabled": true,
    "start": "22:00",
    "end": "07:00"
  },
  "api": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765
  }
}
```

- Time format is 24-hour `HH:MM` local time.
- If `start` time is later than `end`, the lock window is considered overnight (e.g., 22:00–07:00 spans midnight).
- API is disabled by default; enable to start a local REST server on launch (UI or console).

## Build an .exe (optional)

Use PyInstaller:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name pclock main.py
```

Run `dist\pclock.exe`. For scheduler mode, use a console build (omit `--windowed`) if you want logs visible.

## Limitations
- Secure Attention Sequence (Ctrl+Alt+Del), Win+L, and certain OS dialogs are protected by Windows and cannot be blocked by user applications.
- This tool is not a replacement for enterprise kiosk/parental control. Use Windows Assigned Access or third-party products for hardened scenarios.

## License
MIT
