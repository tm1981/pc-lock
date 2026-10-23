import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from config import load_config, verify_password as _verify_password

MAX_BODY = 16 * 1024
# Brute-force protection: after this many bad passwords from one IP, refuse for a while
MAX_AUTH_FAILS = 5
AUTH_BLOCK_SECONDS = 60


class _AuthLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def blocked(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails.get(ip, []) if now - t < AUTH_BLOCK_SECONDS]
            self._fails[ip] = recent
            return len(recent) >= MAX_AUTH_FAILS

    def fail(self, ip: str):
        with self._lock:
            self._fails.setdefault(ip, []).append(time.monotonic())

    def reset(self, ip: str):
        with self._lock:
            self._fails.pop(ip, None)


def schedule_payload() -> dict:
    from schedule_store import read_schedule
    from scheduler import is_snoozed
    sched = read_schedule()
    sched['snoozed'] = is_snoozed(datetime.now(), sched)
    return sched


class _Handler(BaseHTTPRequestHandler):
    locker = None  # injected
    limiter: _AuthLimiter = None  # injected

    def _route(self) -> str:
        return urlsplit(self.path).path.rstrip('/') or '/'

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return None
        if length <= 0:
            return {}
        if length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _auth(self, body: dict) -> bool:
        """Allow Authorization: Bearer <password> OR JSON {"password":"..."}. Sends the error response."""
        ip = self.client_address[0]
        if self.limiter.blocked(ip):
            self._json_response(429, {"error": "too_many_attempts", "retry_after": AUTH_BLOCK_SECONDS})
            return False
        auth = self.headers.get('Authorization') or ''
        if auth.lower().startswith('bearer '):
            pw = auth.split(' ', 1)[1].strip()
        else:
            pw = body.get('password')
        if isinstance(pw, str) and pw and _verify_password(pw):
            self.limiter.reset(ip)
            return True
        self.limiter.fail(ip)
        self._json_response(401, {"error": "unauthorized"})
        return False

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '600')

    def _json_response(self, code: int, payload: dict):
        b = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self._cors_headers()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def _status(self) -> dict:
        st = self.locker.status() if self.locker else {"locked": False, "reason": None, "since": None}
        st["schedule"] = schedule_payload()
        return st

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        route = self._route()
        if route == '/api/status':
            return self._json_response(200, self._status())
        if route == '/api/schedule':
            return self._json_response(200, {"schedule": schedule_payload()})
        return self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        route = self._route()
        if route not in ('/api/lock', '/api/unlock', '/api/schedule'):
            return self._json_response(404, {"error": "not_found"})
        body = self._read_json()
        if body is None:
            return self._json_response(400, {"error": "invalid_json"})
        if not self._auth(body):
            return
        try:
            if route == '/api/lock':
                if self.locker:
                    self.locker.lock_now(reason='manual')
                return self._json_response(200, {"status": "locked", **self._status()})
            if route == '/api/unlock':
                if self.locker:
                    self.locker.unlock_now()
                return self._json_response(200, {"status": "unlocked", **self._status()})
        except Exception as e:
            return self._json_response(500, {"error": str(e)})

        # /api/schedule: partial update, omitted fields keep their current value
        from schedule_store import update_schedule
        from scheduler import parse_hhmm, fmt_hhmm
        changes = {}
        try:
            if 'enabled' in body:
                if not isinstance(body['enabled'], bool):
                    raise ValueError('enabled must be true/false')
                changes['enabled'] = body['enabled']
            for key in ('start', 'end'):
                if key in body:
                    changes[key] = fmt_hhmm(parse_hhmm(body[key]))
            if 'notify_minutes' in body:
                nm = body['notify_minutes']
                if not isinstance(nm, list) or not all(isinstance(n, int) and 0 < n <= 120 for n in nm):
                    raise ValueError('notify_minutes must be a list of minutes (1-120)')
                changes['notify_minutes'] = sorted(set(nm), reverse=True)
        except ValueError as e:
            return self._json_response(400, {"error": f"invalid_schedule: {e}"})
        # Any schedule change cancels a "skip tonight" snooze
        update_schedule(**changes, snooze_until=None)
        return self._json_response(200, {"schedule": schedule_payload()})

    def log_message(self, fmt, *args):
        # Quieter server
        return


class ApiServer:
    def __init__(self, locker, host: str = '127.0.0.1', port: int = 8765):
        self.locker = locker
        self.host = host
        self.port = int(port)
        handler = type('InjectedHandler', (_Handler,), {'locker': locker, 'limiter': _AuthLimiter()})
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name='pclock-api')

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
        finally:
            # Release the port so the server can be restarted with new settings
            self.httpd.server_close()


def maybe_start_api(locker):
    """Start the API if enabled. Returns the server, or None. Raises OSError if the port is taken."""
    try:
        cfg = load_config()
    except Exception:
        return None
    api_cfg = cfg.get('api', {})
    if not api_cfg.get('enabled'):
        return None
    return ApiServer(locker, api_cfg.get('host', '127.0.0.1'), int(api_cfg.get('port', 8765))).start()
