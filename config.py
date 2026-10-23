import hmac
import json
import os
from pathlib import Path
from secrets import token_bytes
from hashlib import pbkdf2_hmac

APP_NAME = 'PC-Lock'


def get_app_dir() -> Path:
    # PCLOCK_APP_DIR lets tests (or a portable install) use a separate data folder
    override = os.environ.get('PCLOCK_APP_DIR')
    if override:
        p = Path(override)
    else:
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
        p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_path() -> Path:
    return get_app_dir() / 'config.json'


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via temp file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _default_config() -> dict:
    return {
        "hotkey": "ctrl+alt+u",
        "password": {
            "salt": None,
            "hash": None,
            "iterations": 200_000,
            "algo": "pbkdf2_sha256",
        },
        "api": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8765,
        }
    }


def load_config() -> dict:
    cfg_path = get_config_path()
    if not cfg_path.exists():
        cfg = _default_config()
        save_config(cfg)
        return cfg
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    # ensure required keys
    d = _default_config()
    d.update(cfg)
    # merge nested
    d["password"] = {**_default_config()["password"], **(cfg.get("password") or {})}
    d["api"] = {**_default_config()["api"], **(cfg.get("api") or {})}
    return d


def save_config(cfg: dict) -> None:
    atomic_write_bytes(get_config_path(), json.dumps(cfg, indent=2).encode('utf-8'))


def has_password() -> bool:
    pwcfg = load_config().get('password', {})
    return bool(pwcfg.get('salt') and pwcfg.get('hash'))


def verify_password(password: str) -> bool:
    cfg = load_config()
    pwcfg = cfg.get('password', {})
    salt_hex = pwcfg.get('salt')
    hash_hex = pwcfg.get('hash')
    iterations = int(pwcfg.get('iterations', 200_000))
    if not salt_hex or not hash_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except Exception:
        return False
    calc = pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return hmac.compare_digest(calc.hex(), str(hash_hex))


def set_password(new_password: str) -> None:
    cfg = load_config()
    salt = token_bytes(16)
    iters = int(cfg.get('password', {}).get('iterations', 200_000))
    h = pbkdf2_hmac('sha256', new_password.encode('utf-8'), salt, iters).hex()
    cfg.setdefault('password', {})['salt'] = salt.hex()
    cfg['password']['hash'] = h
    cfg['password']['iterations'] = iters
    cfg['password']['algo'] = 'pbkdf2_sha256'
    save_config(cfg)


def update_api(enabled: bool, host: str, port: int) -> None:
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('port must be between 1 and 65535')
    cfg = load_config()
    api = cfg.setdefault('api', {})
    api['enabled'] = bool(enabled)
    api['host'] = str(host)
    api['port'] = port
    save_config(cfg)
