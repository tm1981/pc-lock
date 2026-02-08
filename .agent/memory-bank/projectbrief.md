# PC-Lock Project Brief

> **Project**: Windows Desktop Lock Application
> **Language**: Python 3.10+
> **Platform**: Windows only
> **License**: MIT

---

## Overview

**PC-Lock** is a lightweight Windows application that locks the desktop using an **alternate desktop** mechanism (Win32 API). Unlike simple overlay-based locks, this approach provides true input isolation from other applications.

## Core Features

| Feature | Description |
|---------|-------------|
| **Desktop Isolation** | Uses `WinSta0\\LockDesktop` alternate desktop |
| **Multi-Monitor** | Full-screen lock on all displays |
| **Password Protection** | PBKDF2-HMAC-SHA256 with 200k iterations |
| **Daily Scheduling** | Time-based auto-lock with overnight support |
| **REST API** | Remote lock/unlock/schedule control |
| **System Tray** | Background operation with tray icon |
| **Audio Muting** | Automatically mutes system during lock |

## Limitations

- **Ctrl+Alt+Del** - Cannot be blocked (Windows security)
- **Win+L** - OS-level lock still accessible
- **Not enterprise-grade** - Use Windows Assigned Access for kiosk scenarios

## Entry Points

| Command | Result |
|---------|--------|
| `python ui.py` | GUI with tray |
| `python main.py` | Console scheduler |
| `python main.py --lock-now` | Immediate lock |
| `pclock.exe` (built) | GUI mode (default) |
