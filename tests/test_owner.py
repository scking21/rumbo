"""Owner-portal HTTP tests: OAuth endpoints are explicit synthetic transports."""
import base64
import hashlib
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from rumbo.core import Engine
from test_core import contract

try:
    from rumbo.owner import OwnerPortal
except ImportError:
    OwnerPortal = None


@unittest.skipUnless(importlib.util.find_spec('authlib') and importlib.util.find_spec('requests'), 'Install requirements-owner.txt to exercise owner OAuth')
class OwnerPortalTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(OwnerPortal, 'OwnerPortal must provide the separate human-owner workflow')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = [1000.0]
        self.config = dict(owner_resource='https://rumbo.example.com/owner',
            issuer='https://auth.example.com', authorization_endpoint='https://auth.example.com/authorize',
            token_endpoint='https://auth.example.com/token', introspection_url='https://auth.example.com/introspect',
            owner_client_id='owner-client', owner_client_secret_env='RUMBO_TEST_OWNER_SECRET',
            owner_principals=[dict(subject='human-subject', actor='owner', root=str(self.root))])
        self.secret = patch.dict(os.environ, RUMBO_TEST_OWNER_SECRET='synthetic-fixture-secret')
        self.secret.start(); self.addCleanup(self.secret.stop)
        self.claims = dict(active=True, iss=self.config['issuer'], aud=self.config['owner_resource'],
            sub='human-subject', scope='rumbo:owner', exp=5000, nbf=900)
        self.oauth_requests = []
        self.exchange_error = None
        self.provider_status = 200
        self.provider_raw = None
        self.portal = OwnerPortal(self.config, clock=lambda: self.now[0])
        portal = self.portal
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def send(self, status, value=None, headers=None, content_type='application/json'):
                raw = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Content-Type', content_type)
                for key, val in (headers or {}).items():
                    for item in val if isinstance(val, list) else [val]:
                        self.send_header(key, item)
                self.end_headers(); self.wfile.write(raw)
            def do_GET(self):
                if not portal.handle(self): self.send(404, {})
            do_POST = do_GET
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.transport = patch('requests.sessions.Session.send', self.oauth_transport)
        self.transport.start(); self.addCleanup(self.transport.stop)

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def oauth_transport(self, request, **kwargs):
        """A fixture provider, never a production bypass or a real issuer call."""
        from requests import Response
        self.oauth_requests.append((request, kwargs))
        if self.exchange_error:
            raise self.exchange_error
        if request.url == self.config['token_endpoint']:
            data = dict(access_token='synthetic-owner-access-token', token_type='Bearer', refresh_token='synthetic-unused-refresh-token')
        elif request.url == self.config['introspection_url']:
            data = self.claims
        else:
            raise AssertionError('Unexpected OAuth destination: ' + request.url)
        response = Response(); response.status_code = self.provider_status
        response.headers['Content-Type'] = 'application/json'
        response._content = self.provider_raw if self.provider_raw is not None else json.dumps(data).encode()
        response.url = request.url; response.request = request
        response.raw = io.BytesIO(response._content)
        # Session.send normally invokes requests response hooks.
        for hook in request.hooks.get('response', []): hook(response)
        return response

    def request(self, method, path, body=None, cookie=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        hdr = {'Host': 'rumbo.example.com'}
        if cookie: hdr['Cookie'] = cookie
        if headers: hdr.update(headers)
        if isinstance(body, dict):
            body = urlencode(body); hdr.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        conn.request(method, path, body=body, headers=hdr)
        res = conn.getresponse(); data = res.read().decode(); result = res.status, res.getheaders(), data
        conn.close(); return result

    @staticmethod
    def header(response, name):
        return next((v for k, v in response[1] if k.lower() == name.lower()), None)

    @staticmethod
    def cookies(response):
        cookie = SimpleCookie()
        for key, value in response[1]:
            if key.lower() == 'set-cookie': cookie.load(value)
        return cookie

    def login_start(self, cookie=None):
        response = self.request('GET', '/owner/login', cookie=cookie)
        self.assertEqual(response[0], 303, response)
        query = parse_qs(urlsplit(self.header(response, 'Location')).query)
        cookies = self.cookies(response)
        binding = cookies['__Host-rumbo-owner-login'].value
        return query, '__Host-rumbo-owner-login=' + binding, response

    def login(self, previous=None):
        query, cookie, _ = self.login_start(previous)
        response = self.request('GET', '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0])), cookie=cookie + ('; ' + previous if previous else ''))
        self.assertEqual(response[0], 303, response)
        session = self.cookies(response)['__Host-rumbo-owner'].value
        cookie = '__Host-rumbo-owner=' + session
        page = self.request('GET', '/owner', cookie=cookie)
        self.assertEqual(page[0], 200, page)
        csrf = re.search(r'name="csrf" value="([A-Za-z0-9_-]+)"', page[2]).group(1)
        return cookie, csrf, page

    def action(self, cookie, csrf, action, arguments, **extra):
        data = dict(csrf=csrf, action=action, arguments=json.dumps(arguments), confirm='yes', **extra)
        return self.request('POST', '/owner/action', data, cookie, {'Origin': 'https://rumbo.example.com'})

    def test_unauthenticated_routes_never_use_bearer_tokens(self):
        response = self.request('GET', '/owner', headers={'Authorization': 'Bearer agent-token'})
        self.assertEqual(response[0], 401)
        self.assertNotIn('original_request', response[2])
        self.assertEqual(self.request('POST', '/owner/action', {}, headers={'Authorization': 'Bearer agent-token'})[0], 401)
        self.assertEqual(self.oauth_requests, [])

    def test_login_uses_authlib_pkce_owner_audience_and_secure_cookie(self):
        query, _, response = self.login_start()
        self.assertEqual(query['response_type'], ['code'])
        self.assertEqual(query['scope'], ['rumbo:owner'])
        self.assertEqual(query['resource'], [self.config['owner_resource']])
        self.assertEqual(query['redirect_uri'], ['https://rumbo.example.com/owner/callback'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertGreaterEqual(len(query['state'][0]), 32)
        cookie = self.cookies(response)['__Host-rumbo-owner-login']
        self.assertTrue(cookie['secure']); self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax'); self.assertEqual(cookie['path'], '/')
        self.assertEqual(cookie['max-age'], '600')
        self.assertNotIn('code_verifier', query)

    def test_callback_requires_browser_binding_before_exchange(self):
        query, cookie, _ = self.login_start()
        path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0]))
        self.assertEqual(self.request('GET', path)[0], 403)
        self.assertEqual(self.request('GET', path, cookie='__Host-rumbo-owner-login=attacker')[0], 403)
        self.assertEqual(self.oauth_requests, [])
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 303)
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 403)
        self.assertEqual(len(self.oauth_requests), 2)

    def test_callback_rejects_expired_state_and_duplicates_without_exchange(self):
        query, cookie, _ = self.login_start()
        path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0]))
        self.assertEqual(self.request('GET', path + '&state=other', cookie=cookie)[0], 400)
        self.now[0] += 601
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 403)
        self.assertEqual(self.oauth_requests, [])

    def test_verified_callback_exchanges_bound_code_and_rotates_session(self):
        query, binding, _ = self.login_start()
        result = self.request('GET', '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0])), cookie=binding)
        self.assertEqual(result[0], 303)
        self.assertEqual(self.header(result, 'Location'), '/owner')
        cookies = self.cookies(result)
        self.assertEqual(cookies['__Host-rumbo-owner-login']['max-age'], '0')
        session = cookies['__Host-rumbo-owner']
        self.assertTrue(session['secure']); self.assertTrue(session['httponly'])
        self.assertEqual(session['max-age'], '1800')
        request, kwargs = self.oauth_requests[0]
        params = parse_qs(request.body)
        self.assertEqual(params['resource'], [self.config['owner_resource']])
        self.assertEqual(params['grant_type'], ['authorization_code'])
        self.assertEqual(params['code'], ['fixture-code'])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(params['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(challenge, query['code_challenge'][0])
        self.assertEqual(kwargs['timeout'], 5); self.assertFalse(kwargs['allow_redirects'])
        old_cookie = '__Host-rumbo-owner=' + session.value
        new_cookie, _, page = self.login(old_cookie)
        self.assertNotEqual(new_cookie, old_cookie)
        self.assertEqual(self.request('GET', '/owner', cookie=old_cookie)[0], 401)
        self.assertNotIn('synthetic-owner-access-token', page[2])
        self.assertNotIn('synthetic-unused-refresh-token', json.dumps(self.portal.sessions))

    def test_introspection_must_bind_owner_issuer_audience_scope_and_subject(self):
        invalid = [dict(active=False), dict(active=1), dict(iss='https://other.example.com'),
            dict(aud='https://rumbo.example.com/mcp'), dict(aud=[self.config['owner_resource'], 'https://rumbo.example.com/mcp']),
            dict(scope='rumbo:read rumbo:write'), dict(scope='rumbo:owner rumbo:read'),
            dict(sub='unmapped'), dict(exp=1000), dict(exp=True), dict(nbf=1001), dict(exp=None)]
        for change in invalid:
            with self.subTest(change=change):
                original = self.claims.copy(); self.claims.update(change)
                query, binding, _ = self.login_start()
                response = self.request('GET', '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0])), cookie=binding)
                self.assertEqual(response[0], 403, response)
                self.assertNotIn('__Host-rumbo-owner', self.cookies(response))
                self.claims = original

    def test_create_revise_and_decide_use_mapped_actor_and_exact_revisions(self):
        cookie, csrf, page = self.login()
        self.assertIn('Create a contract', page[2])
        self.assertEqual(self.action(cookie, csrf, 'create_contract', contract())[0], 303)
        owner = Engine(self.root, 'owner', 'human')
        self.assertEqual(owner.snapshot()['contract_revision'], 1)
        worker = Engine(self.root, 'maker', 'worker')
        (self.root / 'export.csv').write_text('name,amount\nA,1\n')
        worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))
        worker.execute('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        worker.execute('run_checks', dict(task_id='export', contract_revision=1, artifact_revision=1))
        decision = dict(task_id='export', contract_revision=1, artifact_revision=1, outcome='accepted', reason='I reviewed the result')
        self.assertEqual(self.action(cookie, csrf, 'decide', decision)[0], 303)
        self.assertEqual(owner.snapshot()['tasks'][0]['status'], 'accepted')
        revised = contract(); revised['goal'] = 'Ship revised export'
        self.assertEqual(self.action(cookie, csrf, 'revise_contract', dict(contract=revised, expected_revision=1, reason='Updated scope'))[0], 303)
        self.assertEqual(owner.snapshot()['contract_revision'], 2)
        self.assertEqual(self.action(cookie, csrf, 'decide', decision)[0], 409)
        self.assertEqual(owner.snapshot()['tasks'][0]['status'], 'stale')

    def test_csrf_origin_confirmation_and_identity_spoof_fail_closed(self):
        cookie, csrf, _ = self.login()
        data = dict(csrf=csrf, action='create_contract', arguments=json.dumps(contract()), confirm='yes')
        for headers in ({}, {'Origin': 'https://evil.example.com'}, {'Origin': 'null'}):
            self.assertEqual(self.request('POST', '/owner/action', data, cookie, headers)[0], 403)
        for change in (dict(csrf='wrong'), dict(confirm='no'), dict(confirm=''), dict(actor='evil'), dict(root='/tmp'), dict(role='human')):
            changed = dict(data, **change)
            self.assertIn(self.request('POST', '/owner/action', changed, cookie, {'Origin': 'https://rumbo.example.com'})[0], [400,403])
        injected = dict(contract(), decision_owner='evil')
        self.assertEqual(self.action(cookie, csrf, 'create_contract', injected)[0], 400)
        self.assertEqual(Engine(self.root, 'owner', 'human').snapshot()['events_count'], 0)

    def test_csrf_token_cannot_be_used_with_another_owner_session(self):
        first, csrf, _ = self.login()
        second, _, _ = self.login()
        self.assertNotEqual(first, second)
        self.assertEqual(self.action(second, csrf, 'create_contract', contract())[0], 403)
        self.assertEqual(Engine(self.root, 'owner', 'human').snapshot()['events_count'], 0)

    def test_concurrent_callbacks_cannot_replay_one_login(self):
        import concurrent.futures
        query, cookie, _ = self.login_start()
        path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0]))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.request('GET', path, cookie=cookie)[0], range(2)))
        self.assertEqual(sorted(statuses), [303, 403])
        self.assertEqual(len(self.oauth_requests), 2)

    def test_create_form_uses_server_assigned_owner_without_browser_identity(self):
        from html import unescape
        cookie, csrf, page = self.login()
        value = re.search(r'<textarea[^>]+name="arguments"[^>]*>(.*?)</textarea>', page[2], re.S).group(1)
        args = json.loads(unescape(value))
        self.assertNotIn('decision_owner', args)
        self.assertEqual(self.action(cookie, csrf, 'create_contract', args)[0], 303)
        self.assertEqual(Engine(self.root, 'owner', 'human').snapshot()['decision_owner'], 'owner')

    def test_logout_is_csrf_protected_and_revokes_session(self):
        cookie, csrf, _ = self.login()
        self.assertEqual(self.request('GET', '/owner/logout', cookie=cookie)[0], 405)
        self.assertEqual(self.request('POST', '/owner/logout', dict(csrf=csrf), cookie)[0], 403)
        response = self.request('POST', '/owner/logout', dict(csrf=csrf), cookie, {'Origin': 'https://rumbo.example.com'})
        self.assertEqual(response[0], 303)
        self.assertEqual(self.cookies(response)['__Host-rumbo-owner']['max-age'], '0')
        self.assertEqual(self.request('GET', '/owner', cookie=cookie)[0], 401)

    def test_session_expiry_is_capped_by_token_expiry(self):
        self.claims['exp'] = 1050
        cookie, _, _ = self.login()
        self.now[0] = 1050
        self.assertEqual(self.request('GET', '/owner', cookie=cookie)[0], 401)
        self.claims['exp'] = 99999
        cookie, _, _ = self.login()
        self.now[0] += 1801
        self.assertEqual(self.request('GET', '/owner', cookie=cookie)[0], 401)

    def test_render_escapes_untrusted_context_and_has_no_script_or_frames(self):
        c = contract(); c['original_request'] = '<script>attack()</script>'; c['goal'] = '</textarea><img src=x onerror=attack()>'
        Engine(self.root, 'owner', 'human').execute('create_contract', c)
        _, _, page = self.login()
        self.assertIn('&lt;script&gt;attack()', page[2])
        self.assertNotIn('<script', page[2]); self.assertNotIn('<iframe', page[2])
        self.assertIn('Original request', page[2]); self.assertIn('Acceptance criteria', page[2])
        self.assertIn('frame-ancestors \'none\'', self.header(page, 'Content-Security-Policy'))
        self.assertIn('form-action \'self\'', self.header(page, 'Content-Security-Policy'))
        self.assertEqual(self.header(page, 'Cache-Control'), 'no-store')

    def test_malformed_large_forms_and_duplicate_cookies_are_rejected(self):
        cookie, csrf, _ = self.login()
        self.assertEqual(self.request('GET', '/owner', cookie=cookie + '; ' + cookie)[0], 400)
        self.assertEqual(self.request('POST', '/owner/action', 'a=' + 'a'*270000, cookie, {'Origin': 'https://rumbo.example.com', 'Content-Type': 'application/x-www-form-urlencoded'})[0], 413)
        duplicate = urlencode(dict(csrf=csrf, action='create_contract', arguments=json.dumps(contract()), confirm='yes')) + '&csrf=other'
        self.assertEqual(self.request('POST', '/owner/action', duplicate, cookie, {'Origin': 'https://rumbo.example.com', 'Content-Type': 'application/x-www-form-urlencoded'})[0], 400)
        self.assertEqual(self.action(cookie, csrf, 'delete_project', {})[0], 400)
        nested = urlencode(dict(csrf=csrf, action='create_contract', arguments='['*65+'0'+']'*65, confirm='yes'))
        self.assertEqual(self.request('POST', '/owner/action', nested, cookie, {'Origin': 'https://rumbo.example.com', 'Content-Type': 'application/x-www-form-urlencoded'})[0], 400)

    def test_authenticated_artifact_preview_is_exact_and_escaped(self):
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        worker = Engine(self.root, 'maker', 'worker')
        (self.root / 'export.csv').write_text('name,amount\n<script>attack()</script>')
        worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=60))
        worker.execute('submit_artifact', dict(task_id='export', contract_revision=1, path='export.csv'))
        cookie, _, page = self.login()
        path = '/owner/artifact?task_id=export&contract_revision=1&artifact_revision=1'
        self.assertIn('/owner/artifact?', page[2])
        self.assertEqual(self.request('GET', path)[0], 401)
        preview = self.request('GET', path, cookie=cookie)
        self.assertEqual(preview[0], 200, preview)
        self.assertIn('&lt;script&gt;attack()', preview[2])
        self.assertNotIn('<script', preview[2])
        self.assertIn('Artifact revision 1', preview[2])
        self.assertEqual(self.request('GET', path + '&path=/etc/passwd', cookie=cookie)[0], 400)
        self.assertEqual(self.request('GET', path.replace('artifact_revision=1', 'artifact_revision=2'), cookie=cookie)[0], 409)
        (self.root / 'export.csv').write_text('changed')
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 409)

    def test_wrong_type_check_kind_returns_helpful_error_and_allows_retry(self):
        cookie, csrf, _ = self.login()
        invalid = contract()
        invalid['tasks'][0]['acceptance'][0]['kind'] = []
        response = self.action(cookie, csrf, 'create_contract', invalid)
        self.assertEqual(response[0], 400)
        self.assertIn('BAD_INPUT', response[2])
        self.assertEqual(Engine(self.root, 'owner', 'human').snapshot()['events_count'], 0)
        self.assertEqual(self.action(cookie, csrf, 'create_contract', contract())[0], 303)
        self.assertEqual(Engine(self.root, 'owner', 'human').snapshot()['events_count'], 1)

    def test_login_and_session_storage_are_bounded(self):
        from rumbo.owner import MAX_LOGINS, MAX_SESSIONS
        self.portal.logins = {str(i): {'expires': 1600} for i in range(MAX_LOGINS)}
        self.assertEqual(self.request('GET', '/owner/login')[0], 503)
        self.now[0] = 1601
        query, binding, _ = self.login_start()
        self.portal.sessions = {str(i): {'expires': 2000} for i in range(MAX_SESSIONS)}
        response = self.request('GET', '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0])), cookie=binding)
        self.assertEqual(response[0], 503)
        self.assertNotIn('__Host-rumbo-owner', self.cookies(response))

    def test_duplicate_security_headers_and_callback_issuer_are_rejected(self):
        for name, value in [('Host', 'rumbo.example.com'), ('Cookie', 'x=y'), ('Origin', 'https://rumbo.example.com')]:
            connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
            connection.putrequest('GET', '/owner/login', skip_host=True)
            connection.putheader('Host', 'rumbo.example.com')
            if name != 'Host': connection.putheader(name, value)
            connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 400, name); response.read(); connection.close()
        query, cookie, _ = self.login_start()
        path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0], iss='https://wrong.example.com'))
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 400)
        self.assertEqual(self.oauth_requests, [])

    def test_bad_host_and_missing_configuration_fail_closed(self):
        self.assertEqual(self.request('GET', '/owner/login', headers={'Host': 'evil.example.com'})[0], 403)
        self.secret.stop()
        self.assertEqual(self.request('GET', '/owner/login')[0], 503)
        with self.assertRaises(ValueError): OwnerPortal(dict(self.config, owner_resource='https://rumbo.example.com/mcp'))
        with self.assertRaises(ValueError): OwnerPortal(dict(self.config, owner_principals=[dict(subject='human-subject', actor='owner', root=str(self.root), role='human')]))
        with self.assertRaises(ValueError): OwnerPortal(dict(self.config, token_endpoint='http://localhost/token'))

    def test_provider_redirect_oversize_and_duplicate_claims_fail_closed(self):
        cases = [(302, None), (200, b'{"data":"' + b'x'*65536 + b'"}'),
                 (200, b'{"access_token":"one","access_token":"two","token_type":"Bearer"}')]
        for status, raw in cases:
            with self.subTest(status=status, size=len(raw) if raw else None):
                self.provider_status, self.provider_raw = status, raw
                query, cookie, _ = self.login_start()
                path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0]))
                response = self.request('GET', path, cookie=cookie)
                self.assertEqual(response[0], 403)
                self.assertNotIn('__Host-rumbo-owner', self.cookies(response))

    def test_render_surrogate_text_does_not_crash_http_response(self):
        c = contract(); c['goal'] = 'Malformed unicode \ud800'
        Engine(self.root, 'owner', 'human').execute('create_contract', contract())
        state = Engine(self.root, 'owner', 'human').snapshot(); state['goal'] = c['goal']
        with patch('rumbo.owner.Engine.snapshot', return_value=state): self.login()

    def test_real_mcp_handler_integrates_owner_routes_and_repeated_cookies(self):
        from rumbo.server import create_server
        self.stop_server()
        config = dict(self.config, mode='oauth', public_url='https://rumbo.example.com/mcp',
            introspection_client_id='mcp-client', introspection_secret_env='RUMBO_TEST_OWNER_SECRET',
            principals=[dict(subject='agent-subject', actor='maker', role='worker', root=str(self.root))])
        self.server = create_server('127.0.0.1', 0, config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        import time
        self.claims['exp'] = time.time() + 3600
        cookie, csrf, page = self.login()
        self.assertEqual(self.action(cookie, csrf, 'create_contract', contract())[0], 303)
        response = self.request('POST', '/mcp', json.dumps(dict(jsonrpc='2.0', id=1, method='tools/list')), cookie, {'Content-Type': 'application/json'})
        self.assertEqual(response[0], 401)
        self.assertNotIn('synthetic-owner-access-token', page[2])

    def test_failed_exchange_does_not_leak_error_or_leave_replayable_state(self):
        self.exchange_error = ValueError('secret-provider-response')
        query, cookie, _ = self.login_start()
        path = '/owner/callback?' + urlencode(dict(code='fixture-code', state=query['state'][0]))
        response = self.request('GET', path, cookie=cookie)
        self.assertEqual(response[0], 403)
        self.assertNotIn('secret-provider-response', response[2])
        self.exchange_error = None
        self.assertEqual(self.request('GET', path, cookie=cookie)[0], 403)


class OwnerUnavailableTests(unittest.TestCase):
    def test_missing_configuration_fails_closed_without_optional_imports(self):
        self.assertIsNotNone(OwnerPortal)
        from types import SimpleNamespace
        sent = []
        handler = SimpleNamespace(path='/owner/login', send=lambda *args: sent.append(args))
        with patch('rumbo.owner.importlib.util.find_spec', return_value=None):
            portal = OwnerPortal({})
            self.assertTrue(portal.handle(handler))
        self.assertEqual(sent[0][0], 503)
        handler.path = '/mcp'
        self.assertFalse(portal.handle(handler))


if __name__ == '__main__': unittest.main()
