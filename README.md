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

- Start the scheduler app (runs in the foreground):

```powershell
python main.py
```

- Lock immediately (for testing):

```powershell
python main.py --lock-now
```

- Unlock during lock screen: press `Ctrl+Alt+U`, enter your password, and press Enter.

- To exit the scheduler app, press Ctrl+C in the console.

## Configure schedule

Edit `config.json`:

```json
{
  "hotkey": "ctrl+alt+u",
  "schedule": {
    "enabled": true,
    "start": "22:00",
    "end": "07:00"
  }
}
```

- Time format is 24-hour `HH:MM` local time.
- If `start` time is later than `end`, the lock window is considered overnight (e.g., 22:00–07:00 spans midnight).

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
