# Security Model

## Password Protection

| Aspect | Implementation |
|--------|----------------|
| **Algorithm** | PBKDF2-HMAC-SHA256 |
| **Iterations** | 200,000 |
| **Salt** | 16 bytes random per password |
| **Storage** | Hex-encoded in `config.json` |

```json
"password": {
  "salt": "840e052d9ef29638ee8b040453192f8a",
  "hash": "28e23e726d923bbac5259883cde48e0ffdbfa448...",
  "iterations": 200000,
  "algo": "pbkdf2_sha256"
}
```

## Schedule Protection

Schedule data is encrypted using **Windows DPAPI** (Data Protection API):

- Encrypted with user's Windows credentials
- Stored in `schedule.dat` (binary blob)
- Only readable by the same Windows user
- Prevents schedule tampering via file editing

## Desktop Isolation

The lock screen runs on an **alternate Windows desktop**:

```
WinSta0 (Window Station)
├── Default (normal desktop)
└── LockDesktop (lock screen)
```

**Isolation benefits**:
- Other apps on Default cannot receive input
- Focus stealing prevented
- More robust than overlay-based locks

**Limitations**:
- Secure Attention Sequence (Ctrl+Alt+Del) allowed by design
- Win+L (Windows lock) still functional
- Not a security boundary against privileged processes

## Single Instance

| Mechanism | Implementation |
|-----------|----------------|
| Global mutex | `Global\\PC_LOCK_SINGLETON` via CreateMutexW |
| On duplicate | Brings existing window to front, exits new |

## API Security

| Aspect | Implementation |
|--------|----------------|
| **Binding** | localhost (`127.0.0.1`) by default |
| **Auth** | Same password as unlock |
| **Methods** | Bearer token OR JSON body |
| **CORS** | Enabled for localhost convenience |

**Warning**: Do not expose API on `0.0.0.0` without understanding risks.

## Recommendations

1. Use a strong password (8+ chars, mixed case, numbers)
2. Keep API disabled unless needed
3. Don't rely on this for child/employee restriction (use enterprise tools)
4. Remember Ctrl+Alt+Del always works (by Windows design)
