# Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │    Locker    │  │ scheduler_loop() │  │ CLI arg parsing  │   │
│  │ (state mgmt) │  │ (schedule check) │  │ (--lock-now etc) │   │
│  └──────┬───────┘  └────────┬─────────┘  └──────────────────┘   │
│         │                   │                                    │
│         ▼                   ▼                                    │
│  ┌──────────────────────────────────────┐                       │
│  │         api.py (REST Server)          │                       │
│  │   POST /api/lock, /api/unlock, etc   │                       │
│  └──────────────────────────────────────┘                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
      ┌───────────┐   ┌───────────┐   ┌──────────────┐
      │ ui/       │   │lockscreen │   │ desktop.py   │
      │ (package) │   │   .py     │   │ (Win32 API)  │
      │ GUI+Tray  │   │ (lock UI) │   │              │
      └───────────┘   └───────────┘   └──────────────┘
            │               │               │
            └───────────────┼───────────────┘
                            ▼
                    ┌───────────────┐
                    │  config.py    │
                    │schedule_store │
                    │   .py         │
                    └───────────────┘
```

## Component Relationships

| Component | Depends On | Provides |
|-----------|------------|----------|
| `main.py` | desktop, config, api, schedule_store | Locker, scheduler, CLI |
| `ui/` | main, config, schedule_store, api | GUI package (app, dialogs, tray, scheduler) |
| `lockscreen.py` | desktop, config, screeninfo | LockScreen display |
| `api.py` | config, schedule_store | REST endpoints |
| `desktop.py` | ctypes (Win32) | Desktop switching |
| `config.py` | - | Config persistence, password ops |
| `schedule_store.py` | config | DPAPI-encrypted schedule |

## Process Model

```
┌─────────────────┐         ┌─────────────────────┐
│  Main Process   │ spawn   │  Lockscreen Process │
│  (ui.py or      │ ──────► │  (lockscreen.py)    │
│   main.py)      │         │  on LockDesktop     │
│                 │ ◄────── │                     │
│                 │ watch   │                     │
└─────────────────┘         └─────────────────────┘
```

- Main process stays on Default desktop, manages state
- Lockscreen spawned as subprocess attached to alternate desktop
- Watcher thread monitors subprocess exit for state cleanup
