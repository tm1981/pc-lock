import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from hashlib import pbkdf2_hmac
from datetime import time as dtime, datetime

CONFIG_PATH = Path(__file__).with_name('config.json')


def _load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _verify_password(password: str) -> bool:
    cfg = _load_config()
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
    return calc.hex() == hash_hex


class _Handler(BaseHTTPRequestHandler):
    locker = None  # injected

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length == 0:
            return {}
        try:
            data = self.rfile.read(length)
            return json.loads(data.decode('utf-8'))
        except Exception:
            return {}

    def _auth_ok(self) -> bool:
        # Allow Authorization: Bearer <password> OR JSON {"password":"..."}
        auth = self.headers.get('Authorization')
        if auth and auth.lower().startswith('bearer '):
            pw = auth.split(' ', 1)[1].strip()
            return _verify_password(pw)
        body = getattr(self, '_json', {})
        if isinstance(body, dict) and 'password' in body:
            return _verify_password(str(body.get('password', '')))
        return False

    def _json_response(self, code: int, payload: dict):
        b = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        # CORS for convenience (localhost use)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/status':
            locked = bool(self.locker and self.locker.state.active)
            return self._json_response(200, {"locked": locked})
        return self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        self._json = self._read_json()
        if self.path == '/api/lock':
            if not self._auth_ok():
                return self._json_response(401, {"error": "unauthorized"})
            try:
                if self.locker and not self.locker.state.active:
                    self.locker.lock_now()
                return self._json_response(200, {"status": "locked"})
            except Exception as e:
                return self._json_response(500, {"error": str(e)})
        if self.path == '/api/unlock':
            if not self._auth_ok():
                return self._json_response(401, {"error": "unauthorized"})
            try:
                if self.locker and self.locker.state.active:
                    self.locker.unlock_now()
                return self._json_response(200, {"status": "unlocked"})
            except Exception as e:
                return self._json_response(500, {"error": str(e)})
        return self._json_response(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        # Quieter server
        return


class ApiServer:
    def __init__(self, locker, host: str = '127.0.0.1', port: int = 8765):
        self.locker = locker
        self.host = host
        self.port = int(port)
        handler = type('InjectedHandler', (_Handler,), {})
        handler.locker = locker
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass


def maybe_start_api(locker):
    cfg = _load_config()
    api_cfg = cfg.get('api', {}) if isinstance(cfg, dict) else {}
    enabled = bool(api_cfg.get('enabled', False))
    if not enabled:
        return None
    host = api_cfg.get('host', '127.0.0.1')
    port = int(api_cfg.get('port', 8765))
    server = ApiServer(locker, host, port)
    server.start()
    return server
