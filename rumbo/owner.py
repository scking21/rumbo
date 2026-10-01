"""Separate, operator-mapped OAuth browser workflow for contract owners.

OAuth establishes a configured account identity, not proof of a physical human.
A browser-using agent still needs the user's approval for owner decisions.
Authlib is optional: core/stdio and MCP do not import it or receive these tokens.
"""
import hmac
from html import escape
from http.cookies import SimpleCookie, CookieError
import importlib.util
import ipaddress
import json
import math
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from .core import Engine, RumboError
from .protocol import safe_json

SESSION_COOKIE = '__Host-rumbo-owner'
LOGIN_COOKIE = '__Host-rumbo-owner-login'
MAX_FORM = 256000
MAX_RESPONSE = 65536
MAX_SESSIONS = 1024
MAX_LOGINS = 1024
SESSION_SECONDS = 1800
LOGIN_SECONDS = 600
TOKEN = re.compile(r'^[A-Za-z0-9_-]{32,128}$')
SECURITY_HEADERS = {
    'Cache-Control': 'no-store', 'Pragma': 'no-cache',
    'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
}


def _https_url(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Owner endpoints must be configured public HTTPS URLs')
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.hostname in ('localhost', 'localhost.localdomain')
            or url.hostname.endswith(('.local', '.invalid')) or '\\' in value):
        raise ValueError('Owner endpoints must be configured public HTTPS URLs')
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Private owner endpoints are not allowed')
    try:
        url.port
    except ValueError:
        raise ValueError('Invalid owner endpoint port') from None
    return value


def _pairs(raw, maximum):
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                      encoding='utf-8', errors='strict', max_num_fields=maximum)
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError('Duplicate field')
        data[key] = value
    return data


def _cookie(name, value='', lifetime=0):
    return f'{name}={value}; Max-Age={lifetime}; Path=/; Secure; HttpOnly; SameSite=Lax'


def _bounded_response(response, *args, **kwargs):
    """Requests hook: refuse redirects and cap decoded provider responses."""
    try:
        if response.status_code != 200:
            raise ValueError('OAuth provider request failed')
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if content_type != 'application/json':
            raise ValueError('Expected OAuth JSON response')
        chunks, length = [], 0
        for chunk in response.iter_content(chunk_size=8192):
            length += len(chunk)
            if length > MAX_RESPONSE:
                raise ValueError('OAuth provider response too large')
            chunks.append(chunk)
        response._content = b''.join(chunks)
        response._content_consumed = True
        # Authlib parses again; enforce duplicate/finite-value checks first.
        if not isinstance(safe_json(response._content), dict):
            raise ValueError('Invalid OAuth provider response')
        return response
    finally:
        response.close()


class OwnerPortal:
    """Owner routes for an existing HTTPS host; no signup or credential creation.

    `clock` is constructor-only dependency injection for deterministic tests.
    Production configuration cannot supply transports, identities or bypasses.
    Handler.send accepts bytes and a dict of headers; list values repeat headers.
    """
    def __init__(self, config, *, clock=None):
        self.clock = clock or time.time
        self.lock = threading.RLock()
        self.logins = {}
        self.sessions = {}
        self.enabled = False
        required = ('owner_resource', 'issuer', 'authorization_endpoint', 'token_endpoint',
                    'introspection_url', 'owner_client_id', 'owner_client_secret_env', 'owner_principals')
        # Disabled owner routes never weaken the independent MCP service.
        if any(not config.get(key) for key in required):
            return
        self.resource = _https_url(config['owner_resource'])
        resource = urlsplit(self.resource)
        if resource.path != '/owner':
            raise ValueError('owner_resource must name the separate /owner endpoint')
        self.origin = 'https://' + resource.netloc
        self.host = resource.netloc
        self.callback = self.origin + '/owner/callback'
        if config.get('public_url') and config['public_url'] != self.origin + '/mcp':
            raise ValueError('Owner and MCP resources must share the configured host and remain distinct')
        self.issuer = _https_url(config['issuer'])
        self.authorization_endpoint = _https_url(config['authorization_endpoint'])
        self.token_endpoint = _https_url(config['token_endpoint'])
        self.introspection_url = _https_url(config['introspection_url'])
        self.client_id = config['owner_client_id']
        self.secret_env = config['owner_client_secret_env']
        if (not isinstance(self.client_id, str) or not 1 <= len(self.client_id) <= 512
                or not isinstance(self.secret_env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.secret_env)):
            raise ValueError('Owner client credentials must be externally configured')
        principals = config['owner_principals']
        if not isinstance(principals, list) or not 1 <= len(principals) <= 1000:
            raise ValueError('Configure 1 to 1000 owner principals')
        self.principals = {}
        for principal in principals:
            if not isinstance(principal, dict) or set(principal) != {'subject', 'actor', 'root'}:
                raise ValueError('Owner principal requires only subject, actor and root')
            subject = principal['subject']
            if not isinstance(subject, str) or not 1 <= len(subject) <= 512 or subject in self.principals:
                raise ValueError('Owner subjects must be unique nonempty strings')
            if not isinstance(principal['root'], str):
                raise ValueError('Owner root must be a configured path')
            engine = Engine(principal['root'], principal['actor'], 'human')
            self.principals[subject] = dict(subject=subject, actor=engine.actor, root=str(engine.root))
        self.enabled = True

    def _available(self):
        return self.enabled and bool(os.environ.get(self.secret_env)) and importlib.util.find_spec('authlib') is not None and importlib.util.find_spec('requests') is not None

    def _client(self, state=None):
        from authlib.integrations.requests_client import OAuth2Session
        secret = os.environ.get(self.secret_env)
        if not secret:
            raise ValueError('Owner authentication is not configured')
        client = OAuth2Session(self.client_id, secret, scope='rumbo:owner',
            redirect_uri=self.callback, state=state, code_challenge_method='S256',
            token_endpoint_auth_method='client_secret_basic')
        # Ignore ambient proxy/netrc settings; issuer routing is operator-controlled.
        client.trust_env = False
        return client

    def _prune(self):
        now = self.clock()
        for storage in (self.logins, self.sessions):
            for key in list(storage):
                if storage[key]['expires'] <= now:
                    del storage[key]

    def _send(self, handler, status, message=None, *, html=None, headers=None):
        out = dict(SECURITY_HEADERS)
        out.update(headers or {})
        if html is not None:
            handler.send(status, html.encode('utf-8', errors='replace'), out, 'text/html; charset=utf-8')
        else:
            handler.send(status, {'error': message} if message else None, out)

    def _cookies(self, handler):
        raw = handler.headers.get('Cookie', '')
        if len(raw) > 8192:
            raise ValueError('Cookie too large')
        names = []
        for part in raw.split(';'):
            if '=' in part:
                names.append(part.split('=', 1)[0].strip())
        for name in (SESSION_COOKIE, LOGIN_COOKIE):
            if names.count(name) > 1:
                raise ValueError('Duplicate owner cookie')
        parsed = SimpleCookie()
        parsed.load(raw)
        return {name: parsed[name].value for name in (SESSION_COOKIE, LOGIN_COOKIE) if name in parsed}

    def _session(self, cookies):
        session_id = cookies.get(SESSION_COOKIE, '')
        if not TOKEN.fullmatch(session_id):
            return None
        with self.lock:
            self._prune()
            return self.sessions.get(session_id)

    def handle(self, handler):
        path = urlsplit(handler.path)
        if path.path != '/owner' and not path.path.startswith('/owner/'):
            return False
        if not self._available():
            self._send(handler, 503, 'Owner sign-in is not configured'); return True
        for name in ('Host', 'Cookie', 'Authorization', 'Content-Length', 'Content-Type', 'Origin', 'Transfer-Encoding'):
            if len(handler.headers.get_all(name, [])) > 1:
                self._send(handler, 400, 'Duplicate security-sensitive header'); return True
        if handler.headers.get('Host') != self.host:
            self._send(handler, 403, 'Unrecognized host'); return True
        if len(handler.path) > 8192 or path.fragment:
            self._send(handler, 400, 'Invalid owner request'); return True
        try:
            cookies = self._cookies(handler)
        except (ValueError, CookieError):
            self._send(handler, 400, 'Invalid owner cookie'); return True
        if handler.command == 'GET':
            if path.path == '/owner/callback':
                self._callback(handler, path.query, cookies)
            elif path.path == '/owner/artifact':
                self._artifact(handler, path.query, cookies)
            elif path.query:
                self._send(handler, 400, 'Unexpected owner query')
            elif path.path == '/owner/login':
                self._login(handler)
            elif path.path == '/owner':
                session = self._session(cookies)
                if not session:
                    self._send(handler, 401, html=self._page('Sign in', '<p>Sign in with your configured owner account.</p><p><a href="/owner/login">Sign in</a></p>'))
                else:
                    try:
                        state = Engine(session['root'], session['actor'], 'human').snapshot()
                        self._send(handler, 200, html=self._render(state, session))
                    except (RumboError, OSError):
                        self._send(handler, 503, 'Project state unavailable')
            elif path.path in ('/owner/action', '/owner/logout'):
                self._send(handler, 405, 'Use POST', headers={'Allow': 'POST'})
            else:
                self._send(handler, 404, 'Not found')
        elif handler.command == 'POST' and path.path in ('/owner/action', '/owner/logout') and not path.query:
            self._mutate(handler, path.path, cookies)
        else:
            self._send(handler, 405, 'Method not allowed')
        return True

    def _artifact(self, handler, query, cookies):
        session = self._session(cookies)
        if not session:
            self._send(handler, 401, 'Owner sign-in required'); return
        try:
            args = _pairs(query, 3)
            if set(args) != {'task_id', 'contract_revision', 'artifact_revision'}:
                raise ValueError('Unexpected preview fields')
            for key in ('contract_revision', 'artifact_revision'):
                if not re.fullmatch(r'[1-9][0-9]{0,9}', args[key]):
                    raise ValueError('Invalid artifact revision')
                args[key] = int(args[key])
            view = Engine(session['root'], session['actor'], 'human').artifact_view(args)
        except (ValueError, UnicodeError):
            self._send(handler, 400, 'Invalid artifact preview request'); return
        except RumboError as error:
            status = 409 if error.code in ('STALE_CONTRACT', 'STALE_ARTIFACT', 'ARTIFACT_CHANGED') else 400
            self._send(handler, status, str(error)); return
        except OSError:
            self._send(handler, 503, 'Artifact preview unavailable'); return
        content = '<p><a href="/owner">Back to owner review</a></p><p>' + escape(view['notice']) + '</p><p>Contract revision ' + str(view['contract_revision']) + ' · Artifact revision ' + str(view['artifact_revision']) + '</p><p>SHA-256: ' + escape(view['sha256']) + '</p><pre>' + escape(view['text']) + '</pre>'
        self._send(handler, 200, html=self._page('Inspect ' + view['filename'], content))

    def _login(self, handler):
        with self.lock:
            self._prune()
            if len(self.logins) >= MAX_LOGINS:
                self._send(handler, 503, 'Owner sign-in is busy; try again later'); return
            state = secrets.token_urlsafe(32)
            binding = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            try:
                with self._client(state) as client:
                    url, returned_state = client.create_authorization_url(self.authorization_endpoint,
                        state=state, code_verifier=verifier, resource=self.resource)
                if returned_state != state:
                    raise ValueError('Invalid OAuth state')
            except Exception:
                self._send(handler, 503, 'Owner sign-in is unavailable'); return
            self.logins[state] = dict(binding=binding, verifier=verifier, expires=self.clock() + LOGIN_SECONDS)
        self._send(handler, 303, headers={'Location': url, 'Set-Cookie': _cookie(LOGIN_COOKIE, binding, LOGIN_SECONDS)})

    def _verified(self, claims):
        if not isinstance(claims, dict) or claims.get('active') is not True or claims.get('iss') != self.issuer:
            return None
        # Mixed MCP/owner audiences or scopes are deliberately not an owner credential.
        if claims.get('aud') not in (self.resource, [self.resource]):
            return None
        scope = claims.get('scope')
        if not isinstance(scope, str) or scope.split() != ['rumbo:owner']:
            return None
        exp, nbf = claims.get('exp'), claims.get('nbf', 0)
        now = self.clock()
        if (type(exp) not in (int, float) or not math.isfinite(exp) or exp <= now
                or type(nbf) not in (int, float) or not math.isfinite(nbf) or nbf > now):
            return None
        sub = claims.get('sub')
        principal = self.principals.get(sub) if isinstance(sub, str) else None
        if principal is None:
            return None
        return dict(principal, expires=min(now + SESSION_SECONDS, exp), csrf=secrets.token_urlsafe(32))

    def _callback(self, handler, query, cookies):
        try:
            data = _pairs(query, 4)
            if set(data) - {'code', 'state', 'iss'} or not {'code', 'state'} <= set(data):
                raise ValueError('Invalid callback fields')
            state = data['state']
            if not TOKEN.fullmatch(state) or not 1 <= len(data['code']) <= 2048 or any(c.isspace() for c in data['code']):
                raise ValueError('Invalid callback')
            if 'iss' in data and data['iss'] != self.issuer:
                raise ValueError('Unexpected callback issuer')
        except (ValueError, UnicodeError):
            self._send(handler, 400, 'Invalid owner sign-in response'); return
        with self.lock:
            self._prune()
            login = self.logins.get(state)
            binding = cookies.get(LOGIN_COOKIE, '')
            if not login or not TOKEN.fullmatch(binding) or not hmac.compare_digest(login['binding'], binding):
                self._send(handler, 403, 'Owner sign-in expired or did not match this browser'); return
            # Consume before exchange: races and failed exchanges cannot replay.
            del self.logins[state]
        try:
            with self._client(state) as client:
                options = dict(timeout=5, allow_redirects=False, stream=True, hooks={'response': _bounded_response})
                token = client.fetch_token(self.token_endpoint, code=data['code'],
                    code_verifier=login['verifier'], resource=self.resource,
                    grant_type='authorization_code', **options)
                access = token.get('access_token')
                if not isinstance(access, str) or not 1 <= len(access) <= 8192 or any(c.isspace() for c in access) or str(token.get('token_type', '')).lower() != 'bearer':
                    raise ValueError('Invalid access token')
                response = client.introspect_token(self.introspection_url, token=access,
                    token_type_hint='access_token', **options)
                claims = safe_json(response.content)
                session = self._verified(claims)
            if session is None:
                raise ValueError('Unrecognized owner credential')
        except Exception:
            self._send(handler, 403, 'Owner identity could not be verified', headers={'Set-Cookie': _cookie(LOGIN_COOKIE)}); return
        with self.lock:
            self._prune()
            if len(self.sessions) >= MAX_SESSIONS:
                self._send(handler, 503, 'Owner sign-in is busy; try again later', headers={'Set-Cookie': _cookie(LOGIN_COOKIE)}); return
            self.sessions.pop(cookies.get(SESSION_COOKIE, ''), None)
            session_id = secrets.token_urlsafe(32)
            self.sessions[session_id] = session
        lifetime = max(0, int(session['expires'] - self.clock()))
        self._send(handler, 303, headers={'Location': '/owner', 'Set-Cookie': [
            _cookie(SESSION_COOKIE, session_id, lifetime), _cookie(LOGIN_COOKIE)]})

    def _form(self, handler):
        if handler.headers.get('Transfer-Encoding') or handler.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            return 415, None
        raw_length = handler.headers.get('Content-Length', '')
        if not re.fullmatch(r'[0-9]{1,10}', raw_length):
            return 400, None
        length = int(raw_length)
        if length > MAX_FORM:
            return 413, None
        raw = handler.rfile.read(length)
        if len(raw) != length:
            return 400, None
        try:
            return 200, _pairs(raw.decode('utf-8', errors='strict'), 8)
        except (UnicodeError, ValueError):
            return 400, None

    def _mutate(self, handler, path, cookies):
        session = self._session(cookies)
        if not session:
            self._send(handler, 401, 'Owner sign-in required'); return
        if handler.headers.get('Origin') != self.origin:
            self._send(handler, 403, 'A same-origin owner form is required'); return
        status, form = self._form(handler)
        if form is None:
            self._send(handler, status, 'Invalid owner form'); return
        csrf = form.get('csrf', '')
        if not TOKEN.fullmatch(csrf) or not hmac.compare_digest(session['csrf'], csrf):
            self._send(handler, 403, 'Invalid owner form token'); return
        with self.lock:
            # Expiry/logout cannot race a mutation after authentication checks.
            self._prune()
            if self.sessions.get(cookies.get(SESSION_COOKIE)) is not session:
                self._send(handler, 401, 'Owner sign-in required'); return
            if path == '/owner/logout':
                if set(form) != {'csrf'}:
                    self._send(handler, 400, 'Unexpected logout fields'); return
                del self.sessions[cookies[SESSION_COOKIE]]
                self._send(handler, 303, headers={'Location': '/owner', 'Set-Cookie': _cookie(SESSION_COOKIE)}); return
            if set(form) != {'csrf', 'action', 'arguments', 'confirm'} or form.get('confirm') != 'yes':
                self._send(handler, 400, 'Review the action and confirm it explicitly'); return
            action = form['action']
            if action not in ('create_contract', 'revise_contract', 'decide'):
                self._send(handler, 400, 'Unsupported owner action'); return
            try:
                args = safe_json(form['arguments'])
                if not isinstance(args, dict):
                    raise ValueError('Expected action object')
                if action in ('create_contract', 'revise_contract'):
                    contract = args if action == 'create_contract' else args.get('contract')
                    if not isinstance(contract, dict) or contract.get('decision_owner', session['actor']) != session['actor']:
                        raise ValueError('Owner identity cannot be changed')
                    contract['decision_owner'] = session['actor']
                Engine(session['root'], session['actor'], 'human').execute(action, args)
            except (ValueError, UnicodeError, RecursionError):
                self._send(handler, 400, 'Invalid owner action data'); return
            except RumboError as error:
                status = 409 if error.code in ('STALE_CONTRACT', 'STALE_ARTIFACT', 'ARTIFACT_CHANGED', 'DEPENDENCY_BLOCKED', 'CHECKS_INCOMPLETE', 'CONTRACT_EXISTS') else 400
                self._send(handler, status, str(error)); return
            except OSError:
                self._send(handler, 503, 'Owner action unavailable'); return
        self._send(handler, 303, headers={'Location': '/owner'})

    @staticmethod
    def _page(title, content):
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + escape(title) + ' · Rumbo</title><style>body{font:1rem/1.6 system-ui,sans-serif;max-width:70rem;margin:auto;padding:1.5rem;color:#172033;background:#f7f8fb}section,form{background:white;border:1px solid #ccd3df;border-radius:.5rem;padding:1rem;margin:1rem 0}textarea{display:block;box-sizing:border-box;width:100%;min-height:15rem;font:1rem/1.5 monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin:.7rem 0}button{font:inherit;padding:.5rem 1rem}a{color:#174da2}:focus-visible{outline:3px solid #215dce;outline-offset:3px}h1,h2,h3{line-height:1.2}</style></head><body><header><p>Rumbo · Owner workspace</p></header><main><h1>' + escape(title) + '</h1>' + content + '</main></body></html>'

    @staticmethod
    def _json(value):
        return escape(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))

    def _action_form(self, action, args, csrf, title, context):
        return '<form method="post" action="/owner/action"><h3>' + escape(title) + '</h3><p>' + escape(context) + '</p><input type="hidden" name="csrf" value="' + escape(csrf) + '"><input type="hidden" name="action" value="' + escape(action) + '"><label>Full action JSON<textarea name="arguments" required maxlength="250000" spellcheck="false">' + self._json(args) + '</textarea></label><label><input type="checkbox" name="confirm" value="yes" required> I reviewed this exact action and intend to record it</label><button type="submit">' + escape(title) + '</button></form>'

    def _render(self, state, session):
        csrf = session['csrf']
        content = '<p>Signed in as ' + escape(session['actor']) + '. This session expires within 30 minutes. Evidence and acceptance never authorize unrelated external actions.</p><p>These controls are for the decision owner. Browser automation still requires the owner’s approval.</p><form method="post" action="/owner/logout"><input type="hidden" name="csrf" value="' + escape(csrf) + '"><button type="submit">Sign out</button></form>'
        if not state['contract_revision']:
            example = dict(project_id='my-project', goal='Describe the intended result', original_request='Record the original request', constraints=[], tasks=[dict(id='first-task', title='One bounded task', dependencies=[], acceptance=[dict(id='review', kind='manual_review', prompt='What must an independent reviewer inspect?')])])
            content += '<p>No contract is recorded for your configured workspace. Your account and workspace are provisioned by the service operator.</p>'
            content += self._action_form('create_contract', example, csrf, 'Create a contract', 'Fill in the goal, original request, constraints and bounded acceptance criteria. The server assigns your authenticated account as decision owner.')
            return self._page('Your owner workspace', content)
        content += '<section><h2>Original request</h2><pre>' + escape(state['original_request']) + '</pre><h2>Agreed goal</h2><p>' + escape(state['goal']) + '</p><p>Contract revision ' + str(state['contract_revision']) + '</p><h2>Constraints</h2><pre>' + self._json(state['constraints']) + '</pre></section>'
        for task in state['tasks']:
            content += '<section><h2>' + escape(task['title']) + '</h2><p>Task ' + escape(task['id']) + ' · ' + escape(task['status']) + '</p><p>' + escape(task['stale_reason']) + '</p><h3>Acceptance criteria</h3><pre>' + self._json(task['acceptance']) + '</pre><h3>Recorded artifact</h3><pre>' + self._json(task['artifact']) + '</pre><h3>Evidence and reviewer assertions</h3><pre>' + self._json(task['evidence']) + '</pre><h3>Prior owner decisions</h3><pre>' + self._json(task['decisions']) + '</pre>'
            if task['artifact']:
                preview = '/owner/artifact?' + urlencode(dict(task_id=task['id'], contract_revision=state['contract_revision'], artifact_revision=task['artifact']['revision']))
                content += '<p><a href="' + escape(preview) + '">Inspect these exact artifact bytes</a></p>'
                args = dict(task_id=task['id'], contract_revision=state['contract_revision'], artifact_revision=task['artifact']['revision'], outcome='rejected', reason='')
                content += self._action_form('decide', args, csrf, 'Record a decision', 'Inspect the original goal, criteria and evidence above. Set outcome to accepted or rejected and give an explicit nonempty reason. The decision applies only to these exact contract and artifact revisions. Acceptance requires every current criterion to pass.')
            content += '</section>'
        content += '<section><h2>Decision requests</h2><pre>' + self._json(state['requests']) + '</pre></section>'
        contract = {key: state[key] for key in ('project_id', 'goal', 'original_request', 'constraints')}
        contract['tasks'] = [{key: task[key] for key in ('id', 'title', 'dependencies', 'acceptance')} for task in state['tasks']]
        if state.get('demo'):
            contract['demo'] = True
        content += self._action_form('revise_contract', dict(contract=contract, expected_revision=state['contract_revision'], reason=''), csrf, 'Revise the contract', 'Edit the full contract and give an explicit nonempty reason. The project ID remains fixed. A new revision makes existing work stale until refreshed; it does not delete earlier evidence.')
        return self._page(state['project_id'] + ' · Owner review', content)
