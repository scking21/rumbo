"""Stateless Streamable HTTP MCP with host-owned OAuth subject/project mapping.

Production requires an external OAuth 2.1 authorization server, TLS reverse
proxy and persistent local storage. This module neither creates credentials
nor claims that a configured issuer's consent/login implementation was tested.
"""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlencode, urlsplit
import urllib.request
from .core import Engine, RumboError
from .protocol import Protocol, MAX_MESSAGE, VERSIONS, rpc_error, safe_json
from .owner import OwnerPortal


def https_url(value):
    try:
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or url.query or url.hostname in ('localhost','localhost.localdomain') or url.hostname.endswith(('.local','.invalid')):
            raise ValueError('A configured public HTTPS URL is required')
        try:
            if not ipaddress.ip_address(url.hostname).is_global:
                raise ValueError('Private IP endpoints are not allowed')
        except ValueError as e:
            if str(e)=='Private IP endpoints are not allowed':
                raise
        return value
    except (TypeError,AttributeError):
        raise ValueError('A configured public HTTPS URL is required')


def validate_principals(principals,mode):
    if not isinstance(principals,list) or not 1<=len(principals)<=1000:
        raise ValueError('Configure 1 to 1000 principals')
    seen=set()
    for principal in principals:
        key=principal.get('subject' if mode=='oauth' else 'token')
        if not isinstance(key,str) or not key or key in seen:
            raise ValueError('Principals require unique configured identities')
        seen.add(key)
        if principal.get('role') not in ('worker','reviewer','viewer'):
            raise ValueError('MCP principals cannot acquire human authority')
        if not isinstance(principal.get('actor'),str) or not isinstance(principal.get('root'),str):
            raise ValueError('Principal actor and root are required')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Introspection redirects are not allowed')


class OAuthVerifier:
    def __init__(self,config,clock=None,introspect=None):
        self.resource=https_url(config.get('public_url'))
        self.issuer=https_url(config.get('issuer'))
        self.url=https_url(config.get('introspection_url'))
        self.client_id=config.get('introspection_client_id')
        self.secret_env=config.get('introspection_secret_env')
        if not self.client_id or not self.secret_env:
            raise ValueError('Introspection credentials must be externally configured')
        validate_principals(config.get('principals'),'oauth')
        self.principals={p['subject']:p for p in config['principals']}
        self.clock=clock or time.time
        self.introspect=introspect or self._introspect

    def _introspect(self,token):
        secret=os.environ.get(self.secret_env)
        if not secret:
            raise ValueError('Missing externally supplied introspection credential')
        basic=base64.b64encode((self.client_id+':'+secret).encode()).decode()
        request=urllib.request.Request(self.url,data=urlencode({'token':token,'token_type_hint':'access_token'}).encode(),headers={'Authorization':'Basic '+basic,'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(request,timeout=5) as response:
            raw=response.read(65537)
            if len(raw)>65536:
                raise ValueError('Oversized introspection response')
            return safe_json(raw)

    def verify(self,token):
        if not isinstance(token,str) or not 1<=len(token)<=8192 or any(c.isspace() for c in token):
            return None
        try:
            claims=self.introspect(token)
            if not isinstance(claims,dict) or claims.get('active') is not True or claims.get('iss')!=self.issuer:
                return None
            audience=claims.get('aud')
            if audience!=self.resource and not (isinstance(audience,list) and self.resource in audience):
                return None
            exp=claims.get('exp')
            if type(exp) not in (int,float) or not math.isfinite(exp) or exp<=self.clock():
                return None
            nbf=claims.get('nbf',0)
            if type(nbf) not in (int,float) or not math.isfinite(nbf) or nbf>self.clock():
                return None
            scopes=claims.get('scope','')
            if not isinstance(scopes,str) or 'rumbo:read' not in scopes.split():
                return None
            principal=self.principals.get(claims.get('sub'))
            if not principal:
                return None
            principal=dict(principal)
            if 'rumbo:write' not in scopes.split():
                principal['role']='viewer'
            return principal
        except (OSError,ValueError,TypeError,KeyError,RecursionError):
            return None


class BoundedServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            request.close();return
        try:
            super().process_request(request,address)
        except Exception:
            self.slots.release();raise
    def process_request_thread(self,*args):
        try:
            super().process_request_thread(*args)
        finally:
            self.slots.release()


def create_server(host,port,config):
    mode=config.get('mode')
    if mode not in ('development','oauth','demo'):
        raise ValueError('Explicit development, demo or oauth mode is required')
    if mode in ('development','demo') and host not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Development bearer mode may only bind loopback')
    if mode!='demo':
        validate_principals(config.get('principals'),mode)
    verifier=OAuthVerifier(config) if mode=='oauth' else None
    public=urlsplit(config['public_url']) if verifier else None
    portal=OwnerPortal(config) if mode=='oauth' else None
    if public and public.path!='/mcp':
        raise ValueError('public_url must name the /mcp endpoint')
    for p in config.get('principals',[]):
        Engine(p['root'],p['actor'],p['role']) # validate trusted configuration once at startup
    demo_root=config.get('demo_root')
    demo_engine=None
    if demo_root:
        if mode not in ('development','demo'):
            raise ValueError('Standalone demo UI is local only')
        demo_engine=Engine(demo_root,'demo-viewer','viewer')
        if not demo_engine.snapshot()['demo']:
            raise ValueError('Anonymous local UI is restricted to synthetic demo projects')

    class Handler(BaseHTTPRequestHandler):
        server_version='Rumbo/0.3'
        def setup(self):
            super().setup();self.connection.settimeout(10)
        def log_message(self,*args):
            pass # no request bodies, tokens or source text in default logs
        def send(self,status,value=None,headers=None,content_type='application/json'):
            raw=b'' if value is None else (value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode())
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            for k,v in (headers or {}).items():
                for item in (v if isinstance(v,list) else [v]):
                    self.send_header(k,item)
            self.end_headers()
            if raw:
                self.wfile.write(raw)
        def safe_host(self):
            for header in ('Host','Authorization','Content-Length','Content-Type','Origin','MCP-Protocol-Version'):
                if len(self.headers.get_all(header,[]))>1:
                    self.send(400,{'error':'Duplicate security-sensitive header'});return False
            expected=public.netloc if public else '127.0.0.1:'+str(self.server.server_port)
            allowed={expected}
            if not public:
                allowed.add('localhost:'+str(self.server.server_port))
            if self.headers.get('Host') not in allowed:
                self.send(403,{'error':'Unrecognized host'});return False
            origin=self.headers.get('Origin')
            expected_origin=('https://' if public else 'http://')+expected
            if origin and origin!=expected_origin:
                self.send(403,{'error':'Origin not allowed'});return False
            return True
        def principal(self):
            value=self.headers.get('Authorization','')
            if not value.startswith('Bearer ') or len(value)>8200:
                return None
            token=value[7:]
            if verifier:
                return verifier.verify(token)
            for p in config.get('principals',[]):
                if hmac.compare_digest(hashlib.sha256(token.encode()).digest(),hashlib.sha256(p['token'].encode()).digest()):
                    return p
            return None
        def challenge(self):
            suffix=', resource_metadata="https://'+public.netloc+'/.well-known/oauth-protected-resource"' if public else ''
            self.send(401,{'error':'Authentication required'}, {'WWW-Authenticate':'Bearer realm="rumbo"'+suffix})
        def do_GET(self):
            if not self.safe_host():return
            if portal and portal.handle(self):return
            if self.path in ('/.well-known/oauth-protected-resource','/.well-known/oauth-protected-resource/mcp') and verifier:
                return self.send(200,dict(resource=verifier.resource,authorization_servers=[verifier.issuer],scopes_supported=['rumbo:read','rumbo:write'],bearer_methods_supported=['header']))
            if demo_engine and self.path=='/':
                raw=(Path(__file__).parent/'web/board.html').read_bytes()
                return self.send(200,raw,{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"},'text/html; charset=utf-8')
            if demo_engine and self.path=='/api/state':
                try:
                    state=demo_engine.snapshot()
                    if not state['demo']:
                        return self.send(403,{'error':'Synthetic demo mode is no longer active'})
                    return self.send(200,state)
                except RumboError:return self.send(503,{'error':'Project state unavailable'})
            if self.path=='/mcp':
                if not self.principal():return self.challenge()
                return self.send(405,{'error':'SSE stream not supported; use POST'}, {'Allow':'POST'})
            self.send(404,{'error':'Not found'})
        def do_POST(self):
            if not self.safe_host():return
            if portal and portal.handle(self):return
            if self.path!='/mcp' or mode=='demo':return self.send(404,{'error':'Not found'})
            principal=self.principal()
            if not principal:return self.challenge()
            if self.headers.get('MCP-Protocol-Version',VERSIONS[0]) not in VERSIONS:
                return self.send(400,{'error':'Unsupported MCP protocol version'})
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.send(415,{'error':'Use application/json with Content-Length'})
            try:
                length=int(self.headers.get('Content-Length','-1'))
                if not 0<=length<=MAX_MESSAGE:
                    return self.send(413,{'error':'Request exceeds limit'})
                raw=self.rfile.read(length)
                request=safe_json(raw)
            except (ValueError,UnicodeError,RecursionError):
                return self.send(400,rpc_error(None,-32700,'Invalid JSON'))
            engine=Engine(principal['root'],principal['actor'],principal['role'])
            response=Protocol(engine,oauth=bool(verifier),owner_url=portal.resource if portal and portal.enabled else None).dispatch(request)
            self.send(202 if response is None else 200,response)
        def do_DELETE(self):
            self.send(405,{'error':'Stateless server has no sessions'}, {'Allow':'POST'})
    return BoundedServer((host,port),Handler)
