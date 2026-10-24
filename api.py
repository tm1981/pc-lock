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

    def reserve(self, ip: str) -> bool:
        """Atomically count this attempt as a failure up front (so parallel requests can't
        slip past the limit). Returns False when the IP is blocked. Call reset() on success."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails.get(ip, []) if now - t < AUTH_BLOCK_SECONDS]
            if len(recent) >= MAX_AUTH_FAILS:
                self._fails[ip] = recent
                return False
            recent.append(now)
            self._fails[ip] = recent
            return True

    def reset(self, ip: str):
        with self._lock:
            self._fails.pop(ip, None)


def schedule_payload() -> dict:
    from schedule_store import read_schedule
    from scheduler import is_snoozed
    sched = read_schedule()
    sched['snoozed'] = is_snoozed(datetime.now(), sched)
    return sched


LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


class _Handler(BaseHTTPRequestHandler):
    locker = None  # injected
    limiter: _AuthLimiter = None  # injected
    bind_host = '127.0.0.1'  # injected
    cors_origins: frozenset = frozenset()  # injected; empty = no CORS (server-side callers only)

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
        if not self.limiter.reserve(ip):
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
        self._json_response(401, {"error": "unauthorized"})
        return False

    def _request_allowed(self) -> bool:
        """Block DNS rebinding (localhost-bound server reached via a foreign Host name) and
        browser requests from origins that aren't explicitly allowed. Sends the error response."""
        if self.bind_host in LOCAL_HOSTS:
            host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]').lower()
            if host not in LOCAL_HOSTS:
                self._json_response(403, {"error": "forbidden_host"})
                return False
        origin = self.headers.get('Origin')
        if origin and origin.rstrip('/') not in self.cors_origins:
            self._json_response(403, {"error": "forbidden_origin"})
            return False
        return True

    def _cors_headers(self):
        origin = (self.headers.get('Origin') or '').rstrip('/')
        if origin and origin in self.cors_origins:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
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

    def _status(self, with_schedule: bool) -> dict:
        st = self.locker.status() if self.locker else {"locked": False, "reason": None, "since": None}
        if with_schedule:
            st["schedule"] = schedule_payload()
        return st

    def do_OPTIONS(self):
        if not self._request_allowed():
            return
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if not self._request_allowed():
            return
        route = self._route()
        if route == '/api/status':
            # Lock state is public (used as an "online" check); schedule details need auth
            if self.headers.get('Authorization'):
                if not self._auth({}):
                    return
                return self._json_response(200, self._status(True))
            return self._json_response(200, self._status(False))
        if route == '/api/schedule':
            if not self._auth({}):
                return
            return self._json_response(200, {"schedule": schedule_payload()})
        return self._json_response(404, {"error": "not_found"})

    def do_POST(self):
        if not self._request_allowed():
            return
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
                return self._json_response(200, {"status": "locked", **self._status(True)})
            if route == '/api/unlock':
                if self.locker:
                    self.locker.unlock_now()
                return self._json_response(200, {"status": "unlocked", **self._status(True)})
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
    def __init__(self, locker, host: str = '127.0.0.1', port: int = 8765, cors_origins=()):
        self.locker = locker
        self.host = host
        self.port = int(port)
        handler = type('InjectedHandler', (_Handler,), {
            'locker': locker, 'limiter': _AuthLimiter(), 'bind_host': host,
            'cors_origins': frozenset(o.rstrip('/') for o in cors_origins),
        })
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
    # Optional "cors_origins": ["http://..."] in config.json for browser callers; default none
    origins = api_cfg.get('cors_origins')
    return ApiServer(locker, api_cfg.get('host', '127.0.0.1'), int(api_cfg.get('port', 8765)),
                     origins if isinstance(origins, list) else []).start()
