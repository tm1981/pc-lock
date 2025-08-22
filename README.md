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
- Change schedule and click "Save schedule" (you will be asked for the current password)
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

- POST /api/schedule
  - Body: `{ "password": "your_password", "enabled": true, "start": "22:00", "end": "07:00" }`
  - Response: `{ "schedule": { "enabled": true, "start": "22:00", "end": "07:00" } }`

Examples (PowerShell):

```powershell
# Lock
curl -Method POST -Uri http://127.0.0.1:8765/api/lock -ContentType application/json -Body '{"password":"YOURPASS"}'

# Unlock
curl -Method POST -Uri http://127.0.0.1:8765/api/unlock -ContentType application/json -Body '{"password":"YOURPASS"}'

# Status
curl http://127.0.0.1:8765/api/status

# Update schedule
curl -Method POST -Uri http://127.0.0.1:8765/api/schedule -ContentType application/json -Body '{"password":"YOURPASS","enabled":true,"start":"22:00","end":"07:00"}'
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
- The schedule is stored securely (DPAPI) in `schedule.dat`; manual edits to `config.json` will not change the active schedule.

## Build a standalone .exe

We support a single self-contained exe using PyInstaller. It can run the console scheduler (default), the GUI, or the internal lock screen mode.

```powershell
pip install pyinstaller
# Optional: ensure tray deps
pip install -r requirements.txt

# Build icon asset
python make_icon.py

# Build single exe (embed the app icon and ship the tray icon asset)
pyinstaller --noconfirm --onefile --windowed --name pclock --icon assets\pclock.ico --add-data assets\pclock.ico;assets main.py
```

Run:
- Double-click .\dist\pclock.exe (GUI launches by default on the exe)
- Manual lock now (from exe):
  - .\dist\pclock.exe --lock-now

Notes:
- The exe relaunches itself in an internal lock screen mode when needed (no external python files required).
- The tray icon uses assets\pclock.ico when available; it is embedded via --add-data.
- If Windows Firewall prompts when enabling API on 0.0.0.0, allow access for your network.

## Limitations
- Secure Attention Sequence (Ctrl+Alt+Del), Win+L, and certain OS dialogs are protected by Windows and cannot be blocked by user applications.
- This tool is not a replacement for enterprise kiosk/parental control. Use Windows Assigned Access or third-party products for hardened scenarios.

## License
MIT
