# PC Lock (Windows)

A lightweight Windows app that locks the desktop by switching to an alternate desktop and showing a full-screen message on all monitors. Unlock requires a hotkey followed by a password.

Notes:
- Implemented in Python using Win32 APIs via `ctypes`.
- Modern dark theme GUI built with CustomTkinter.
- Uses an alternate desktop (WinSta0\\LockDesktop) to isolate input from other apps. CTRL+ALT+DEL is still available by design (cannot be blocked by user apps).
- Simple daily schedule with toast notification warnings.

## Features
- Modern dark theme UI with CustomTkinter (Dark/Light/System themes).
- Lock/unlock via alternate desktop (robust vs. simple overlays).
- Full-screen, always-on-top lock screen across monitors.
- Configurable unlock hotkey (default: Ctrl+Alt+U).
- Password-protected unlock (PBKDF2-HMAC with per-install salt).
- Daily lock window scheduling with **toast notifications** (5 min and 1 min warnings).
- Optional REST API (localhost by default) to lock/unlock remotely with password auth.
- System tray integration for background operation.

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
python main.py --ui
```

- Click "Lock now" to test
- Change schedule and click "Save schedule" (you will be asked for the current password)
- When schedule is enabled, you'll receive **toast notifications** 5 minutes and 1 minute before lock
- Change password requires the current password
- Use the Theme dropdown to switch between Dark, Light, or System themes
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
  - Response: `{ "schedule": { "enabled": true, "start": "22:00", "end": "07:00", "notify_minutes": [5, 1] } }`
  - Note: `notify_minutes` is read-only via API; configure notification timing through the UI.

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
- Toast notification timing (default: 5 min and 1 min before lock) is stored with the schedule, not in `config.json`.

## Build a standalone .exe

We support packaging using PyInstaller. **Note:** CustomTkinter requires `--onedir` mode (not `--onefile`) because it includes theme/font assets.

```powershell
pip install pyinstaller
pip install -r requirements.txt

# Build icon asset
python make_icon.py

# Find customtkinter location
pip show customtkinter
# Note the Location path, e.g.: c:\users\...\site-packages

# Build (replace <CTK_PATH> with the customtkinter folder path from above)
pyinstaller --noconfirm --onedir --windowed ^
  --name pclock ^
  --icon assets\pclock.ico ^
  --add-data "assets\pclock.ico;assets" ^
  --add-data "<CTK_PATH>\customtkinter;customtkinter" ^
  main.py
```

Example with typical path:
```powershell
pyinstaller --noconfirm --onedir --windowed --name pclock --icon assets\pclock.ico --add-data "assets\pclock.ico;assets" --add-data "C:\Users\tm81\miniconda3\Lib\site-packages\customtkinter;customtkinter" main.py
```

Run:
- Double-click `.\\dist\\pclock\\pclock.exe` (GUI launches by default)
- Manual lock: `.\\dist\\pclock\\pclock.exe --lock-now`

Notes:
- The exe relaunches itself in an internal lock screen mode when needed.
- The tray icon uses assets\\pclock.ico when available; it is embedded via --add-data.
- If Windows Firewall prompts when enabling API on 0.0.0.0, allow access for your network.
- **Cannot use `--onefile`** due to CustomTkinter's bundled .json and .otf theme files.

## Limitations
- Secure Attention Sequence (Ctrl+Alt+Del), Win+L, and certain OS dialogs are protected by Windows and cannot be blocked by user applications.
- This tool is not a replacement for enterprise kiosk/parental control. Use Windows Assigned Access or third-party products for hardened scenarios.

## License
MIT
