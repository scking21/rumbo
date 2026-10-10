"""Optional WorkOS Connect profile: verified JWT identity plus active introspection.

No WorkOS account, client, credential or permission is created here. Two
preconfigured clients/resources are mandatory; dynamic-client scope fallback is
intentionally unsupported. The generic OAuth path remains independent.
"""
import base64
import hmac
import ipaddress
import importlib.util
import math
import os
import re
import threading
import time
from urllib.parse import urlencode, urlsplit
import urllib.request

from .protocol import safe_json

MAX_TOKEN = 16384
MAX_PROVIDER_RESPONSE = 65536
KEY_TTL = 300
KEY_REFRESH_INTERVAL = 30


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Provider redirects are forbidden')


def _fetch_json(url, method='GET', data=None, headers=None):
    """Fixed operator-selected HTTPS destinations only. Never logs credentials."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    with opener.open(request, timeout=5) as response:
        if response.status != 200:
            raise ValueError('Provider response failed')
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if content_type not in ('application/json', 'application/jwk-set+json'):
            raise ValueError('Provider did not return JSON')
        raw = response.read(MAX_PROVIDER_RESPONSE + 1)
        if len(raw) > MAX_PROVIDER_RESPONSE:
            raise ValueError('Provider response too large')
        result = safe_json(raw)
        if not isinstance(result, dict):
            raise ValueError('Provider response must be an object')
        return result


def _origin(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError('A public HTTPS issuer origin is required')
    u = urlsplit(value)
    if u.scheme != 'https' or not u.hostname or u.path != '' or u.query or u.fragment or u.username or u.password or u.hostname.endswith(('.invalid', '.local', '.localhost')) or u.hostname == 'localhost' or '\\' in value:
        raise ValueError('A public HTTPS issuer origin is required')
    try:
        if not ipaddress.ip_address(u.hostname).is_global:
            raise ValueError('Private issuer addresses are not supported')
    except ValueError as error:
        if str(error) == 'Private issuer addresses are not supported':
            raise
    try:
        u.port
    except ValueError:
        raise ValueError('Invalid issuer port') from None
    return value.rstrip('/')


def _resource(value, path):
    if not isinstance(value, str):
        raise ValueError('Configure separate MCP and owner HTTPS resources')
    u = urlsplit(value)
    origin = _origin('https://' + u.netloc) if u.scheme == 'https' else None
    if not origin or u.path != path or u.query or u.fragment or u.username or u.password:
        raise ValueError('Configure separate MCP and owner HTTPS resources')
    return origin + path


def _jwt_parts(token):
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token):
        raise ValueError('Invalid compact JWT')
    try:
        parts = token.split('.')
        decoded = [safe_json(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))) for p in parts[:2]]
        if not all(isinstance(part, dict) for part in decoded):
            raise ValueError('JWT header and claims must be objects')
        return decoded
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('Invalid JWT JSON') from None


class WorkOSConnectVerifier:
    def __init__(self, config, kind, *, clock=None, fetch_json=None):
        if importlib.util.find_spec('jwt') is None or importlib.util.find_spec('cryptography') is None:
            raise ValueError('Install requirements-authkit.txt for the WorkOS profile')
        if kind not in ('mcp', 'owner'):
            raise ValueError('Unknown WorkOS resource kind')
        self.kind = kind
        self.issuer = _origin(config.get('issuer'))
        self.mcp_resource = _resource(config.get('public_url'), '/mcp')
        self.owner_resource = _resource(config.get('owner_resource'), '/owner')
        if urlsplit(self.mcp_resource).netloc != urlsplit(self.owner_resource).netloc:
            raise ValueError('Owner and MCP resources must share the approved public host')
        self.resource = self.mcp_resource if kind == 'mcp' else self.owner_resource
        mcp_client, owner_client = config.get('introspection_client_id'), config.get('owner_client_id')
        if not all(isinstance(c, str) and re.fullmatch(r'client_[A-Za-z0-9_-]{1,120}', c) for c in (mcp_client, owner_client)) or mcp_client == owner_client:
            raise ValueError('Two distinct predefined WorkOS client IDs are required')
        self.client_id = mcp_client if kind == 'mcp' else owner_client
        self.secret_env = config.get('introspection_secret_env' if kind == 'mcp' else 'owner_client_secret_env')
        if not isinstance(self.secret_env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.secret_env):
            raise ValueError('An existing client-secret environment reference is required')
        for key, suffix in [('introspection_url', '/oauth2/introspection'), ('authorization_endpoint', '/oauth2/authorize'), ('token_endpoint', '/oauth2/token')]:
            if config.get(key) != self.issuer + suffix:
                raise ValueError('WorkOS endpoints must exactly match the configured issuer')
        self.introspection_url = config['introspection_url']
        self.jwks_url = self.issuer + '/oauth2/jwks'
        self.fetch_json = fetch_json or _fetch_json
        self.clock = clock or time.time
        self.lock = threading.Lock()
        self.keys = {}
        self.fetched_at = None
        self.last_attempt = None

    def _key(self, kid):
        import jwt
        with self.lock:
            now = self.clock()
            expired = self.fetched_at is None or now - self.fetched_at >= KEY_TTL
            may_refresh = self.last_attempt is None or now - self.last_attempt >= KEY_REFRESH_INTERVAL
            unknown_refresh = kid not in self.keys and may_refresh
            if expired and not may_refresh:
                raise ValueError('Signing-key refresh unavailable')
            if expired or unknown_refresh:
                # Failed refreshes never renew trust in stale keys.
                self.last_attempt = now
                raw = self.fetch_json(self.jwks_url, headers={'Accept': 'application/json'})
                keys = raw.get('keys') if isinstance(raw, dict) else None
                if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
                    self.keys = {}; raise ValueError('Invalid JWKS')
                parsed = {}
                for value in keys:
                    if not isinstance(value, dict):
                        self.keys = {}; raise ValueError('Invalid JWK')
                    key_id = value.get('kid')
                    if not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key_id) or key_id in parsed:
                        self.keys = {}; raise ValueError('Missing or duplicate key ID')
                    if value.get('kty') != 'RSA' or value.get('alg', 'RS256') != 'RS256' or value.get('use', 'sig') != 'sig' or value.get('key_ops', ['verify']) != ['verify'] or any(k in value for k in ('d','p','q','dp','dq','qi','jku','x5u')):
                        self.keys = {}; raise ValueError('Unsupported signing key')
                    key = jwt.PyJWK.from_dict(value, algorithm='RS256').key
                    if not 2048 <= key.key_size <= 8192:
                        self.keys = {}; raise ValueError('Unsupported RSA key size')
                    parsed[key_id] = key
                self.keys = parsed
                self.fetched_at = now
            if kid not in self.keys:
                raise ValueError('Unknown signing key')
            return self.keys[kid]

    def _decode(self, token, audience):
        import jwt
        try:
            header, _ = _jwt_parts(token)
            if header.get('alg') != 'RS256' or set(header) - {'alg','kid','typ'} or header.get('typ', 'JWT') != 'JWT':
                raise ValueError('Unsupported token header')
            kid = header.get('kid')
            if not isinstance(kid, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', kid):
                raise ValueError('Missing signing key ID')
            claims = jwt.decode(token, self._key(kid), algorithms=['RS256'], issuer=self.issuer, audience=audience,
                                options={'require': ['iss','aud','sub','exp','iat']})
            if claims.get('aud') not in (audience, [audience]):
                raise ValueError('Mixed audience is not accepted')
            now = self.clock()
            for name in ('exp','iat','nbf'):
                value = claims.get(name, 0)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('Invalid numeric date')
            if claims['exp'] <= now or claims['iat'] > now or claims.get('nbf', 0) > now:
                raise ValueError('Token outside validity period')
            if not isinstance(claims['sub'], str) or not re.fullmatch(r'user_[A-Za-z0-9_-]{1,120}', claims['sub']):
                raise ValueError('A mapped user token is required; M2M is unsupported')
            return claims
        except (jwt.PyJWTError, OSError, TypeError, ValueError, KeyError, RecursionError):
            raise ValueError('Token signature or claims could not be verified') from None

    def verify_access(self, token):
        claims = self._decode(token, self.resource)
        for field in ('sid','jti'):
            if not isinstance(claims.get(field), str) or not 1 <= len(claims[field]) <= 256:
                raise ValueError('A user-consent access token is required')
        if claims.get('client_id') != self.client_id:
            raise ValueError('Wrong predefined client')
        scope = claims.get('scope')
        if not isinstance(scope, str):
            raise ValueError('Signed scope is required')
        scopes = scope.split()
        if len(scopes) != len(set(scopes)):
            raise ValueError('Duplicate scopes')
        allowed = {'rumbo:read','rumbo:write','offline_access'} if self.kind == 'mcp' else {'openid','rumbo:owner'}
        required = {'rumbo:read'} if self.kind == 'mcp' else allowed
        if not required <= set(scopes) or not set(scopes) <= allowed:
            raise ValueError('Unexpected or insufficient signed scopes')
        secret = os.environ.get(self.secret_env)
        if not secret:
            raise ValueError('Missing existing introspection credential')
        body = urlencode(dict(client_id=self.client_id, client_secret=secret, token=token, token_type_hint='access_token')).encode()
        active = self.fetch_json(self.introspection_url, method='POST', data=body,
                                 headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        if not isinstance(active, dict) or active.get('active') is not True or active.get('token_type') != 'access_token':
            raise ValueError('Inactive access token')
        for field in ('iss','aud','sub','client_id','exp','iat','sid','jti'):
            if field not in active or active[field] != claims[field] or type(active[field]) is not type(claims[field]):
                raise ValueError('Introspection does not match the verified token')
        if 'scope' in active and active['scope'] != scope:
            raise ValueError('Introspection scope conflicts with signed scope')
        if active['exp'] <= self.clock():
            raise ValueError('Token expired during introspection')
        return dict(claims, active=True)

    def verify_owner(self, access_token, id_token, nonce):
        if self.kind != 'owner' or not isinstance(nonce, str) or not nonce:
            raise ValueError('Owner nonce is required')
        access = self.verify_access(access_token)
        identity = self._decode(id_token, self.client_id)
        if identity['sub'] != access['sub'] or not isinstance(identity.get('nonce'), str) or not hmac.compare_digest(identity['nonce'], nonce):
            raise ValueError('Owner identity/nonce mismatch')
        # openid is used only to bind the browser login; it grants no Rumbo action.
        return dict(access, scope='rumbo:owner', exp=min(access['exp'], identity['exp']))
