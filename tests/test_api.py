import json
import urllib.error
import urllib.request

import pytest

import api
from config import set_password
from schedule_store import read_schedule, write_schedule


class FakeLocker:
    def __init__(self):
        self.locked = False

    def status(self):
        return {"locked": self.locked, "reason": "manual" if self.locked else None, "since": None}

    def lock_now(self, reason='manual', **kw):
        self.locked = True

    def unlock_now(self, snooze=True):
        self.locked = False


@pytest.fixture
def server():
    set_password('secret1')
    srv = api.ApiServer(FakeLocker(), '127.0.0.1', 0).start()
    srv.base = f'http://127.0.0.1:{srv.httpd.server_address[1]}'
    yield srv
    srv.stop()


def call(srv, method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(srv.base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b'{}')


def test_no_cors_by_default_and_foreign_origins_rejected(server):
    code, headers, body = call(server, 'GET', '/api/status')
    assert code == 200 and 'Access-Control-Allow-Origin' not in headers
    assert body['locked'] is False and 'schedule' not in body  # schedule needs auth
    assert call(server, 'POST', '/api/lock', {'password': 'secret1'}, {'Origin': 'https://evil.example'})[0] == 403


def test_allowlisted_origin_gets_cors():
    set_password('secret1')
    srv = api.ApiServer(FakeLocker(), '127.0.0.1', 0, cors_origins=['http://pc-control.lan:3000']).start()
    srv.base = f'http://127.0.0.1:{srv.httpd.server_address[1]}'
    try:
        code, headers, _ = call(srv, 'GET', '/api/status', headers={'Origin': 'http://pc-control.lan:3000'})
        assert code == 200 and headers['Access-Control-Allow-Origin'] == 'http://pc-control.lan:3000'
    finally:
        srv.stop()


def test_dns_rebinding_host_rejected(server):
    assert call(server, 'GET', '/api/status', headers={'Host': 'attacker.example'})[0] == 403


def test_schedule_reads_need_auth(server):
    assert call(server, 'GET', '/api/schedule')[0] == 401
    code, _, body = call(server, 'GET', '/api/status', headers={'Authorization': 'Bearer secret1'})
    assert code == 200 and 'schedule' in body
    assert call(server, 'GET', '/api/schedule', headers={'Authorization': 'Bearer secret1'})[0] == 200


def test_parallel_guesses_cannot_exceed_limit(server):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(20) as ex:
        codes = list(ex.map(lambda _: call(server, 'POST', '/api/lock', {'password': 'x'})[0], range(20)))
    assert codes.count(401) == api.MAX_AUTH_FAILS and codes.count(429) == 20 - api.MAX_AUTH_FAILS


def test_lock_unlock_with_bearer(server):
    auth = {'Authorization': 'Bearer secret1'}
    assert call(server, 'POST', '/api/lock', {}, auth)[2]['locked'] is True
    assert call(server, 'POST', '/api/unlock', {}, auth)[2]['locked'] is False


def test_bruteforce_is_throttled(server):
    for _ in range(api.MAX_AUTH_FAILS):
        assert call(server, 'POST', '/api/lock', {'password': 'x'})[0] == 401
    assert call(server, 'POST', '/api/lock', {'password': 'secret1'})[0] == 429


def test_partial_schedule_update(server):
    write_schedule(True, '22:00', '07:00', notify_minutes=[10])
    code, _, body = call(server, 'POST', '/api/schedule', {'password': 'secret1', 'start': '21:30'})
    assert code == 200
    s = read_schedule()
    assert (s['enabled'], s['start'], s['end'], s['notify_minutes']) == (True, '21:30', '07:00', [10])
    assert call(server, 'POST', '/api/schedule', {'password': 'secret1', 'start': '25:00'})[0] == 400


def test_query_string_and_bad_json(server):
    assert call(server, 'GET', '/api/status?x=1')[0] == 200
    assert call(server, 'POST', '/api/lock', raw=b'{bad')[0] == 400


def test_server_can_restart_on_same_port():
    srv = api.ApiServer(FakeLocker(), '127.0.0.1', 0).start()
    port = srv.httpd.server_address[1]
    srv.stop()
    api.ApiServer(FakeLocker(), '127.0.0.1', port).start().stop()
